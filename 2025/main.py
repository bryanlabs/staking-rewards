from datetime import datetime, timedelta
import json
import requests
import os

# Fill these out with addresses you want to get data for
osmosis_address = [
    {
        "name": "",
        "address": "" 
    }
]


def main():

    eth_date_prices = {}
    with open("reference_data/ethereum_2024-01-01_2024-12-31.csv", "r") as f:
        lines = f.readlines()
        for line in lines[1:]:
            line = line.strip().split(",")
            date = line[0]
            op = float(line[2])
            high = float(line[3])
            low = float(line[4])
            close = float(line[5])
            eth_date_prices[date] = {
                "open": op,
                "high": high,
                "low": low,
                "close": close,
            }

    osmo_price_data = {}
    with open("reference_data/osmosis_2024-01-01_2024-12-31.csv", "r") as f:
        lines = f.readlines()
        for line in lines[1:]:
            line = line.strip().split(",")
            date = line[0]
            op = float(line[2])
            high = float(line[3])
            low = float(line[4])
            close = float(line[5])
            osmo_price_data[date] = {
                "open": op,
                "high": high,
                "low": low,
                "close": close,
            }

    if not os.path.exists("interim_data"):
        os.makedirs("interim_data")

    with open("interim_data/eth_prices_parsed.json", "w") as jf:
        jf.write(json.dumps(eth_date_prices))

    with open("interim_data/osmo_prices_parsed.json", "w") as jf:
        jf.write(json.dumps(osmo_price_data))

    eth_lines = []
    with open("reference_data/eth_val_table_dump.txt", "r") as f:
        lines = f.readlines()

        # lines are chunked as follows:
        # 1. epoch
        # 2. block height
        # 3. days and hours ago
        # 4. validator account
        # 5. ETH withdrawn
        # We want to change the text file into a CSV
        # The date needs to be changed into a date string instead of days ago
        dates = {}

        with open("interim_data/eth_val_table_dump.csv", "w") as f:

            # Write the header
            f.write("epoch,slot,date,validator account,ETH withdrawn\n")

            # Write the data
            for i in range(0, len(lines), 5):
                epoch = lines[i].strip()
                slot = lines[i + 1].strip()
                days_ago = lines[i + 2].strip()

                # Convert days ago to a date string
                days_ago = days_ago.split(" ")
                days = int(days_ago[0])
                hours = int(days_ago[2])

                # Convert days and hours to a date string
                date = datetime.now() - timedelta(days=days, hours=hours)
                dateStr = date.strftime("%Y-%m-%d %H:%M:%S")

                validator_account = lines[i + 3].strip()
                eth_withdrawn = lines[i + 4].strip()

                f.write(
                    f"{epoch},{slot},{dateStr},{validator_account},{eth_withdrawn}\n"
                )

                eth_lines.append([epoch, slot, date, validator_account, eth_withdrawn])

        with open("interim_data/dates.txt", "w") as f:
            for date in dates:
                f.write(f"{date}\n")

    eth_lines_combined = [
        {
            "date": eth_lines[0][2].strftime("%Y-%m-%d"),
            "full_date": eth_lines[0][2],
            "eth_withdrawn": float(eth_lines[0][4].split(" ")[0]),
            "epoch": eth_lines[0][0],
        }
    ]

    for line in eth_lines:

        if line[2].strftime("%Y-%m-%d") == eth_lines_combined[-1]["date"]:
            eth_lines_combined[-1]["eth_withdrawn"] += float(line[4].split(" ")[0])
        else:
            eth_lines_combined.append(
                {
                    "date": line[2].strftime("%Y-%m-%d"),
                    "full_date": line[2],
                    "eth_withdrawn": float(line[4].split(" ")[0]),
                    "epoch": line[0],
                }
            )

    eth_out = []    
    with open("interim_data/eth_out_split.csv", "w") as f:
        f.write("timeReceived,currencyReceived,quantityReceived,usdValue\n")
        for line in eth_lines:
            if line[2].year != 2024:
                continue
            dateStr = line[2].strftime("%Y-%m-%d")
            ethPrice = eth_date_prices[dateStr]["high"]
            ethAmount = float(line[4].split(" ")[0])
            ethValue = "{:.2f}".format(round(ethAmount * ethPrice, 2))
            epoch = line[0]
            eth_out.append([dateStr, "ETH", ethAmount, ethValue, f"ETH epoch: {epoch}"])
            f.write(f"{line[2]},ETH,{ethAmount},{ethValue}\n")

    with open("interim_data/eth_out_combined.csv", "w") as f:
        f.write("timeReceived,currencyReceived,quantityReceived,usdValue\n")
        for line in eth_lines_combined:
            if line["full_date"].year != 2024:
                continue
            dateStr = line["date"]
            ethPrice = eth_date_prices[dateStr]["high"]
            ethAmount = float(line["eth_withdrawn"])
            ethValue = "{:.2f}".format(round(ethAmount * ethPrice, 2))
            f.write(f"{dateStr},ETH,{ethAmount},{ethValue}\n")

    if not os.path.exists("output_data"):
        os.makedirs("output_data")

    for address in osmosis_address:
        # check if file is already in interim data
        try:
            with open(f"interim_data/{address['address']}.csv", "r") as f:
                pass
        except FileNotFoundError:
            get_osmosis_csv(address["address"])

        address_lines = []
        with open(f"interim_data/{address['address']}.csv", "r") as f:
            lines = f.readlines()

            # Write the header
            with open(f"interim_data/{address['address']}_parsed.csv", "w") as f:
                f.write("timeReceived,currencyReceived,quantityReceived,usdValue,operationId\n")

                for line in lines[1:]:
                    line = line.strip().split(",")

                    if line[0] == "withdraw" and line[8] == "staked":

                        date = line[1]
                        parsed_date = datetime.strptime(date, "%m/%d/%Y %H:%M:%S")
                        if parsed_date.year != 2024:
                            continue

                        date_str = parsed_date.strftime("%Y-%m-%d")
                        quantity = line[2]
                        currency = line[3]
                        operationId = line[9]

                        usd_value = "{:.2f}".format(round(osmo_price_data[date_str]['high'] * float(quantity)))

                        f.write(f"{date_str},{currency},{quantity},{usd_value},{operationId}\n")
                        address_lines.append([date_str, currency, quantity, usd_value, f"OSMO TX: {operationId}"])

        with open(f"output_data/{address['name']}_parsed.csv", "w") as f:
            f.write("timeReceived,currencyReceived,quantityReceived,usdValue,operationId\n")

            if address["name"] == "BryanVentures":
                address_lines = address_lines + eth_out
                address_lines = sorted(address_lines, key=lambda x: datetime.strptime(x[0], "%Y-%m-%d"))

            symbol_totals = {}
            for line in address_lines:
                if line[1] not in symbol_totals:
                    symbol_totals[line[1]] = 0
                symbol_totals[line[1]] += float(line[3])
                f.write(f"{line[0]},{line[1]},{line[2]},{line[3]},{line[4]}\n")

            f.write("\n")
            for symbol in symbol_totals:
                f.write(f"{symbol},{'{:.2f}'.format(round(symbol_totals[symbol], 2))}\n")

def get_osmosis_csv(address):

    url = "https://cosmos-tax.bryanlabs.net/events.csv"

    data = {
        "addresses": address,
        "format": "accointing"
    }

    response = requests.post(url, data=json.dumps(data), headers={"Content-Type": "application/json"}, timeout=None)

    response.raise_for_status()

    with open(f"interim_data/{address}.csv", "w") as f:
        f.write(response.text)


if __name__ == "__main__":
    main()
