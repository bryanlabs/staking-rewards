# Cost-Calc Script

Run this script on an Accointing Excel export file and it will reach out to [CoinGecko](https://www.coingecko.com/) to get the costs of symbols according to the following metrics:

* Specific classifications such as `staked` or `airdrops`
* Based on the date column for specific years

It will then output a new file with all the original rows except for a few differences:

* A new column `usdValue`
* For every row that matched the metric, this column will be filled out with the following formula: `<Symbol cost on that date in USD> * <number of coins of that symbol> = usdValue`

As a fallback option, if CoinGecko does not provide full time-range coverage for all Symbol + Date combinations, the script will reach out to Coinhall (a Terra price tracker). This will only work for missing Terra symbols.

# Requirements

* Python 3+
* Python packages: The script requires some imports
    * `requests` for reaching out to the CoinGecko API
    * `openpyxl` for reading and writing Excel files.
    * You can install these into your Python environment by running `python -m pip install -r requirements.txt`
* A preconfigured CoinGecko Coins config JSON file
    * Containing the following:
        * A dictionary with keys of Symbols (as found in your Accointing export)
        * The values of these keys must contain CoinGecko information relating to the CoinGecko API request for that symbol
    * A preconfigured list already comes with the package, make sure to check that out to see the default configuration and make sure it matches up to your use-case
    * The values must contain the ID used by CoinGecko for the corresponding symbol
    * E.g.

```
{
    "DAI": {
        "id": "dai",
        "symbol": "dai",
        "name": "Dai"
    },
    "ADA": {
        "id": "cardano",
        "symbol": "ada",
        "name": "Cardano"
    },
    "ANC": {
        "id": "anchor-protocol",
        "symbol": "anc",
        "name": "Anchor Protocol"
    },
    ...
}
```

* You can check and/or add new values to this config file by running the following command and analyzing the output `coingecko_coins.json` file. You would then add new Symbol/config pairs for any Symbol you want

```
python -c "import json; import requests; print(json.dumps(requests.get('https://api.coingecko.com/api/v3/coins/list').json(), indent=4))" > coingecko_coins.json
```

* A CoinHall symbol config json file is required as well
    * If using certain Terra coins, CoinGecko may not cover them. The code falls back on Coinhall if CoinGecko did not provide coverage
    * Containing the following:
        * A dictionary with keys of Symbols (as found in your Accointing export)
        * The values of these keys must contain Coinhall information relating to the Coinhall API request for that symbol
        * Coinhall tracks the symbol by Terra pair address, see the Coinhall implementation for details
```
#e.g.
{
    "MINE": {
        "id": "terra178jydtjvj4gw8earkgnqc80c3hrmqj4kw2welz", #Symbol pair address
        "symbol": "mine",
        "name": "Pylon Protocol"
    },
    "PSI": {
        "id": "terra163pkeeuwxzr0yhndf8xd2jprm9hrtk59xf7nqf",
        "symbol": "psi",
        "name": "Nexus Protocol"
    },
    "LOOP": {
        "id": "terra106a00unep7pvwvcck4wylt4fffjhgkf9a0u6eu",
        "symbol": "loop",
        "name": "LOOP Finance"
    },
    ...
}
```

# How to run

The script takes a few configuration options, some with defaults, some without. You can see all the options by running `python cost_calc.py -h`

The required options are as follows:

* `-i` The input Excel file path to process
* `-o` The output Excel file path to create
* `-cgstoid` The configuration JSON file path for the CoinGecko symbols to ids configuration
* `-chstoid` The configuration JSON file path for the Coinhall symbols to ids configuration


So, to run you would do something like this:

`python staking-rewards.py -i path/to/input.xlsx -o path/to/output.xlsx -cgstoid path/to/coingecko/config.json -chstoid path/to/coinhall/config.json`

You will then need to examine the output file to confirm the process worked after it has finished.

# Gotchas

The script is 100% reliant on the CoinGecko API. This comes with 2 gotchas:

1. CoinGecko stores data on their servers for every coin. **If CoinGecko does not have data for a specific symbol on a specific date, this script will NOT be able to get the cost.** When this happens, the script will output the Excel lines so you can fill in the gaps where needed.
2. If you forget to put a symbol config value in your `config.json` file, the script will **NOT** be able to fill in the cost for that symbol. Symbol names are not unique, so these cannot be reliad on to find the correct cost from CoinGecko.
3. CoinGecko has a rate-limit and there is no current way to provide and API key if you pay for a higher rate-limit. You will have to wait at least a few minutes (depending on how many transactions are being processed)

The script has a fallback API request structure that will reach out to Coinhall for symbols that do not have coverage in CoinGecko. This comes 2 with gotchas:

1. Coinhall is Terra specific, it will not provide coverage outside of Terra coins
2. Coinhall tracks price in quotes by uusd and pair address - Terra provides pair addresses that Coinhall uses to track Open/High/Low/Close values.


