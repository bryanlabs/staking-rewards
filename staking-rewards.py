import requests
import time
import sys
import json
import argparse
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from os.path import exists
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
import datetime
import traceback

COIN_GECKO_API_URL = "https://api.coingecko.com/api/v3"
COIN_GECKO_COINS_ENDPOINT = "/coins"
COIN_GECKO_HISTORICAL_ENDPOINT = "/<coin-id>/history"

#this represents CoinGecko's 50 requests/minute API rate limit, plus some seconds for variance
COIN_GECKO_REQUEST_CHUNKS = 9
COIN_GECKO_THROTTLE_TIME = 61

#this represents throttling for Coinhall, which will throttle after every single request
COINHALL_THROTTLE_TIME = 10
COINHALL_API_URL = "https://api.coinhall.org/api/v1"
COINHALL_CHART_ENDPOINT = "/charts/terra/candles"
COINHALL_HISTORICAL_PARAMS = "?bars=1&from=<from-time>&to=<to-time>&quoteAsset=uusd&interval=1d&pairAddress=<coin-id>"

KEY_CLASSIFICATIONS = ["staked", "airdrop"]

class CaughtError(Exception):
    pass

def parse_args():
    parser = argparse.ArgumentParser(description='Get the cost-basis in USD (from CoinGecko) for your staking and airdrop rewards from Accointing export data')
    parser.add_argument('--input-file', '-i', help='The location of your Accointing input file', required=True)
    parser.add_argument('--output-file', '-o', help='The location of your output file', required=True)
    parser.add_argument('--coingecko-symbol-to-id-file', '-cgstoid', help='The location of your CoinGecko JSON config file that stores symbols to ID configurations for making API requests', required=True)
    parser.add_argument('--coinhall-symbol-to-id-file', '-chstoid', help='The location of your CoinHall JSON config file that stores symbols to ID configurations for making API requests', required=True)
    parser.add_argument('--symbol-column', '-sc', help='The column in the EXCEL that stores the symbol of interest', default="boughtCurrency")
    parser.add_argument('--value-column', '-vc', help='The column in the EXCEL that stores the symbol of interest', default="boughtQuantity")
    parser.add_argument('--date-column', '-dc', help='The column in the EXCEL that stores the symbol of interest', default="timeExecuted")
    parser.add_argument('--year-filter', '-yf', help='The year to gather data for', default=2022, type=int)
    parser.add_argument('--coingecko-cache', '-cg-c', help='The JSON file holding cached data from CoinGecko (used in subsequent runs)', default="./.coingecko_cache.json", type=str)
    args = parser.parse_args()
    return args

def validate_args(args):
    if not exists(args.input_file):
        raise CaughtError(f"No file exists at {args.input_file} for the input data file, please enter a correct filepath")

    if exists(args.output_file):
        answer = input("Output file already exists, would you like to overwrite it? (Y/n) >> ")
        if answer != "Y":
            raise CaughtError("Exiting...")
    
    if not exists(args.coingecko_symbol_to_id_file):
        raise CaughtError(f"No file exists at {args.coingecko_symbol_to_id_file} for the CoinGecko symbol to id configuration file, please enter a correct filepath")
    
    if not exists(args.coinhall_symbol_to_id_file):
        raise CaughtError(f"No file exists at {args.coinhall_symbol_to_id_file} for the Coinhall symbol to id configuration file, please enter a correct filepath")

def get_coingecko_cache(coingecko_cache_file):
    if not exists(coingecko_cache_file):
        print(f"No CoinGecko price cache file found at {coingecko_cache_file}, creating...")
        with open(coingecko_cache_file, 'w') as fp:
            json.dump({}, fp)
        return {}
    else:
        print(f"Found CoinGecko cache file {coingecko_cache_file}, loading...")
        return json.load(open(coingecko_cache_file))

def write_coingecko_cache(data, coingecko_cache_file):
    with open(coingecko_cache_file, 'w') as fp:
        json.dump(data, fp)

def load_config_file(fname):
    return json.load(open(fname))

def parse_input_data(fname):
    print("Loading data from Excel file")
    wb = None
    try:
        wb = load_workbook(filename=fname)
    except InvalidFileException:
        raise CaughtError(f"Input file '{fname}' is not in the correct Excel format, please check your file and try again")

    ws = wb.active
    rows = ws.rows
    headers = [c.value for c in next(rows)]
    active_sheet_name = ws.title
    return active_sheet_name, headers, [row for row in iter_worksheet(ws)]

def iter_worksheet(worksheet):
    # It's necessary to get a reference to the generator, as 
    # `worksheet.rows` returns a new iterator on each access.
    rows = worksheet.rows

    # Get the header values as keys and move the iterator to the next item
    keys = [c.value for c in next(rows)]
    for row in rows:
        values = [c.value for c in row]
        yield dict(zip(keys, values))

def get_key_data_point_indexes(rows, dateColumn, yearFilter):
    print("Gathering key data points for classifications", KEY_CLASSIFICATIONS)
    return [index for index, row in enumerate(rows) if "classification" in row and row["classification"] in KEY_CLASSIFICATIONS and row[dateColumn].year == yearFilter and row["boughtCurrency"]]

def process_rows(rows, key_data_point_indexes, coingecko_symbols_to_id_configs, coinhall_symbols_to_id_configs, date_column, symbolColumn, valueColumn, simplified_rows_headers, coingecko_cache, coingecko_cache_file):

    print(f"Processing {len(key_data_point_indexes)} rows that matched the metric")

    symbols_to_dates_to_rows = {}

    #build data structure storing symbols to dates to row indexes
    #used for ease-of-access and processing
    for i in key_data_point_indexes:
        row = rows[i]
        boughtCurrency = row[symbolColumn]
        if boughtCurrency not in symbols_to_dates_to_rows:
            symbols_to_dates_to_rows[boughtCurrency] = {}

        date_key = row[date_column].strftime("%d-%m-%Y")

        if date_key not in symbols_to_dates_to_rows[boughtCurrency]:
            symbols_to_dates_to_rows[boughtCurrency][date_key] = [i]
        else:
            symbols_to_dates_to_rows[boughtCurrency][date_key].append(i)

    symbols_to_dates_to_costs = {}

    #gather the cached CoinGecko costs so we dont attempt to grab them again
    print("Checking CoinGecko cache file for cached data...")
    num_cached = 0
    for symbol in symbols_to_dates_to_rows:
        for date in symbols_to_dates_to_rows[symbol]:
            if symbol in coingecko_cache and date in coingecko_cache[symbol]:
                num_cached += 1
                if symbol not in symbols_to_dates_to_costs:
                    symbols_to_dates_to_costs[symbol] = {}
                symbols_to_dates_to_costs[symbol][date] = coingecko_cache[symbol][date]

    if num_cached > 0:
        print(f"Found {num_cached} entries, these will be skipped when reaching out to CoinGecko")
    else:
        print(f"No cached entries found, all data needs to be retrieved")

    #remove the cached entries
    for symbol in symbols_to_dates_to_costs:
        for date in symbols_to_dates_to_costs[symbol]:
            del symbols_to_dates_to_rows[symbol][date]
        # if len(symbols_to_dates_to_rows[symbol].keys()) == 0:
        #     del symbols_to_dates_to_rows[symbol]
    
    #loop through chunks of data and send to API for processing
    print("Reaching out to CoinGecko for symbol cost data, this may take a while...")

    coingecko_requests_made = 0
    for symbol in symbols_to_dates_to_rows:

        if symbol not in symbols_to_dates_to_costs:
                symbols_to_dates_to_costs[symbol] = {}

        request_url = get_coingecko_request_url(symbol, coingecko_symbols_to_id_configs)

        for date in symbols_to_dates_to_rows[symbol]:
            if symbol in coingecko_cache and date in coingecko_cache[symbol]:
                symbols_to_dates_to_costs[symbol][date] = coingecko_cache[symbol][date]
                continue
            else:
                symbols_to_dates_to_costs[symbol][date] = None
                if request_url:
                    parameterized_url = add_coingecko_request_params(request_url, date)
                    resp = requests.get(parameterized_url)

                    try:
                        resp.raise_for_status()
                    except Exception as err:
                        if resp.status_code == 429:
                            print("A CoinGecko API throttle error occurred, self-throttling and trying again")
                            time.sleep(COIN_GECKO_THROTTLE_TIME)
                            resp = requests.get(parameterized_url)
                            coingecko_requests_made = 1

                            #give up after 1 retry
                            try:
                                resp.raise_for_status()
                            except Exception as err:
                                write_coingecko_cache(coingecko_cache, coingecko_cache_file)
                                print("CoinGecko API call failed", err)
                                raise CaughtError(f"CoinGecko API call failed, subsequent runs will use the cache file at {coingecko_cache_file} to start from this checkpoint")
                        else:
                            write_coingecko_cache(coingecko_cache, coingecko_cache_file)
                            print("CoinGecko API call failed", err)
                            raise CaughtError(f"CoinGecko API call failed, subsequent runs will use the cache file at {coingecko_cache_file} to start from this checkpoint")
                        
                    #safely get a None value if the json structure is not found in response
                    #this was found during testing of some symbols where they store data but not the USD cost on that date
                    symbol_date_cost = resp.json().get("market_data", {}).get("current_price", {}).get("usd")
                    symbols_to_dates_to_costs[symbol][date] = symbol_date_cost

                    if symbol in coingecko_cache:
                        coingecko_cache[symbol][date] = symbols_to_dates_to_costs[symbol][date]
                    else:
                        coingecko_cache[symbol] = {}
                        coingecko_cache[symbol][date] = symbols_to_dates_to_costs[symbol][date]

                    write_coingecko_cache(coingecko_cache, coingecko_cache_file)

                    coingecko_requests_made += 1
                    #self-throttling to stay under CoinGecko throttle limits
                    if coingecko_requests_made == COIN_GECKO_REQUEST_CHUNKS:
                        coingecko_requests_made = 0
                        time.sleep(COIN_GECKO_THROTTLE_TIME)
                    else:
                        time.sleep(1)
                else:
                    print("Your CoinGecko symbol config list does not support symbol", symbol)

    write_coingecko_cache(coingecko_cache, coingecko_cache_file)
    print("Finished reaching out to CoinGecko")

    missing_coingecko_coverage = {}

    for i in key_data_point_indexes:
        row = rows[i]

        boughtCurrency = row[symbolColumn]
        date_key = row[date_column].strftime("%d-%m-%Y")

        try:
            row["usdValue"] = symbols_to_dates_to_costs[boughtCurrency][date_key] * row[valueColumn]
        except:
            missing_coingecko_coverage[i] = {"symbol": boughtCurrency, "date": row[date_column]}

        rows[i] = row

    missing_coinhall_coverage = {}
    if missing_coingecko_coverage:
        print("CoinGecko does not provide coverage for the following Symbol + Date combinations:")
        for index in missing_coingecko_coverage:
            print(f"\tSymbol: {missing_coingecko_coverage[index]['symbol']}\t\tDate: {missing_coingecko_coverage[index]['date']}\t\t(Excel Row {index + 2})")

        print("Attempting Coinhall fallback API")

        index_to_costs = {}
        print("Reaching out to Coinhall for symbol cost data, this may take a while...")
        for index in missing_coingecko_coverage:
            symbol = missing_coingecko_coverage[index]['symbol']
            date = missing_coingecko_coverage[index]['date']
            
            request_url = get_coinhall_request_url(symbol, coinhall_symbols_to_id_configs)

            if request_url:
                parameterized_url = add_coinhall_request_params(request_url, date, coinhall_symbols_to_id_configs[symbol]["id"])
                resp = make_coinhall_api_request(parameterized_url, "Error reaching out to CoinGecko, please try again later:", COINHALL_THROTTLE_TIME)
                data = resp.json()
                if data and len(data) > 0:
                    index_to_costs[index] = data[0]
                else:
                    missing_coinhall_coverage[index] = {"symbol": symbol, "date": date}
                time.sleep(COINHALL_THROTTLE_TIME)
            else:
                print("Your Coinhall symbol config list does not support symbol", symbol)
                missing_coinhall_coverage[index] = {"symbol": symbol, "date": date}
        
        print("Finished reaching out to Coinhall")
        for index in index_to_costs:
            row = rows[index]
            row["usdValue"] = index_to_costs[index]["high"] * row[valueColumn]
            rows[index] = row

        if missing_coinhall_coverage:
            print("CoinHall does not provide coverage for the following Symbol + Date combinations:")
            for index in missing_coinhall_coverage:
                row = rows[index]
                row["usdValue"] = 0
                rows[index] = row
                print(f"\tSymbol: {missing_coinhall_coverage[index]['symbol']}\t\tDate: {missing_coinhall_coverage[index]['date']}\t\t(Excel Row {index + 2})")
        else:
            print("CoinHall provided coverage for all CoinGecko missing symbol/date combinations")
    else:
        print("CoinGecko provided coverage for all symbol/date combinations")
    

    simplified_rows = []

    for index in key_data_point_indexes:
        row = rows[index]
        simplified_row = {header: row[header] for header in simplified_rows_headers}
        if index in missing_coinhall_coverage:
            simplified_row["comment"] = "Not covered, fixme"
        else:
            simplified_row["comment"] = ""
        simplified_rows.append(simplified_row)



    return rows, simplified_rows

#creates chunks of symbols and dates to send for API processing
def chunk_symbols_and_dates(symbols_to_dates, len_chunks):

    values = {}
    length = 0
    for key in symbols_to_dates:
        for date in symbols_to_dates[key]:
            if key in values:
                values[key].append(date)
                length+=1
            else:
                values[key] = [date]
                length+=1
            if length == len_chunks:
                yield values
                values = {}
                length = 0

    #last yield returns last chunk
    yield values

def get_coingecko_request_url(symbol, coingecko_symbols_to_id_configs):
    coingecko_request_id = None
    coingecko_request_url = None

    if symbol in coingecko_symbols_to_id_configs:
        coingecko_request_id = coingecko_symbols_to_id_configs[symbol]["id"]
        coingecko_request_url =  COIN_GECKO_API_URL + COIN_GECKO_COINS_ENDPOINT + COIN_GECKO_HISTORICAL_ENDPOINT.replace("<coin-id>", coingecko_request_id)

    return coingecko_request_url

def add_coingecko_request_params(request_url, date):
    return request_url + f"?date={date}"

def get_coinhall_request_url(symbol, coinhall_symbols_to_id_configs):
    coinhall_request_url = None

    if symbol in coinhall_symbols_to_id_configs:
        coinhall_request_url =  COINHALL_API_URL + COINHALL_CHART_ENDPOINT

    return coinhall_request_url

def add_coinhall_request_params(request_url, date, symbol_id):
    from_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = from_date.replace(hour=11, minute=59, second=59)

    from_unix = str(int(time.mktime(from_date.timetuple())))
    to_unix = str(int(time.mktime(to_date.timetuple())))

    return request_url + COINHALL_HISTORICAL_PARAMS.replace("<from-time>", from_unix).replace("<to-time>", to_unix).replace("<coin-id>", symbol_id)

def make_coinhall_api_request(request_url, error_string, throttle_time):
    resp = requests.get(request_url)
    try:
        resp.raise_for_status()
    except requests.HTTPError as err:
        #if throttled, wait for the throttle to end and retry
        if resp.status_code == 429:
            time.sleep(throttle_time)
            resp = requests.get(request_url)

            #give up after 1 retry
            try:
                resp.raise_for_status()
            except Exception as err:
                print(error_string, err)
                sys.exit(1)
        else:
            print(error_string, err)
            sys.exit(1)
    except Exception as err:
        print(error_string, err)
        sys.exit(1)

def output_rows(title, headers, rows, fname, sum_header=None):
    print("Creating new Excel file", fname)
    wb = Workbook()
    ws1 = wb.active
    ws1.title = title

    ws1.append(headers)

    for row in rows:
        data = []
        for header in headers:
            if header in row:
                data.append(row[header])
            else:
                data.append(None)
        ws1.append(data)

    if sum_header and sum_header in headers:
        index = headers.index(sum_header) + 1
        column = get_column_letter(index)

        first_row = column + "2"
        last_row = column + str(len(ws1[column]))

        sum_formula = f"= SUM({first_row}:{last_row})"

        sum_formula_cell = column + str(len(ws1[column]) + 1)
        ws1[sum_formula_cell] = sum_formula

    wb.save(fname)

def main():
    args = parse_args()
    validate_args(args)

    coingecko_cache = get_coingecko_cache(args.coingecko_cache)

    #Curated list of CoinGecko Symbols to IDs in a JSON file
    #These will correspond to the symbols found in your CSV column -> CoinGecko's data structure for corresponding symbol
    #e.g.
    # {
    #     "DAI": {
    #         "id": "dai",
    #         "symbol": "dai",
    #         "name": "Dai"
    #     },
    #     "ADA": {
    #         "id": "cardano",
    #         "symbol": "ada",
    #         "name": "Cardano"
    #     },
    #     ...
    # }
    coingecko_symbols_to_id_configs = load_config_file(args.coingecko_symbol_to_id_file)

    #Curated list of Coinhall Symbols to IDs in a JSON file
    #Coinhall provides coverage for various Terra Symbols by pairAddress
    #These will correspond to the symbols found in your CSV column -> Coinhalls's data structure for corresponding symbol
    #e.g.
    # {
    #      "MINE": {
    #         "id": "terra178jydtjvj4gw8earkgnqc80c3hrmqj4kw2welz",
    #         "symbol": "mine",
    #         "name": "Pylon Protocol"
    #     },
    #     "PSI": {
    #         "id": "terra163pkeeuwxzr0yhndf8xd2jprm9hrtk59xf7nqf",
    #         "symbol": "psi",
    #         "name": "Nexus Protocol"
    #     },
    #     "LOOP": {
    #         "id": "terra106a00unep7pvwvcck4wylt4fffjhgkf9a0u6eu",
    #         "symbol": "loop",
    #         "name": "LOOP Finance"
    #     },
    #     ...
    # }
    coinhall_symbols_to_id_configs = load_config_file(args.coinhall_symbol_to_id_file)

    title, headers, rows = parse_input_data(args.input_file)
    key_data_point_indexes = get_key_data_point_indexes(rows, args.date_column, args.year_filter)
    simplified_rows_headers = [args.date_column, args.symbol_column, args.value_column, "usdValue"]
    rows, simplified_rows = process_rows(rows, key_data_point_indexes, coingecko_symbols_to_id_configs, coinhall_symbols_to_id_configs, args.date_column, args.symbol_column, args.value_column, simplified_rows_headers, coingecko_cache, args.coingecko_cache)
    headers.append("usdValue")
    simplified_rows_headers.append("comment")
    output_rows(title, headers, rows, args.output_file)
    output_rows(title, simplified_rows_headers, simplified_rows, args.output_file + "-simplified.xlsx", sum_header="usdValue")

if __name__ == "__main__":
    try:
        main()
    except CaughtError as err:
        print(err)
    except Exception as err:
        print("An unanticipated error occured, please contact the developer to assist (provide the following stack trace)")
        traceback.print_exc()
        print(err)