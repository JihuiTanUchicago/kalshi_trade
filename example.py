import requests
import uuid
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
import asyncio

from clients import KalshiHttpClient, KalshiWebSocketClient, Environment

# Load environment variables
load_dotenv()
env = Environment.DEMO if os.getenv('ENVIRONMENT') == "DEMO" else Environment.PROD
KEYID = os.getenv('DEMO_KEYID') if env == Environment.DEMO else os.getenv('PROD_KEYID')
KEYFILE = os.getenv('DEMO_KEYFILE') if env == Environment.DEMO else os.getenv('PROD_KEYFILE')

try:
    with open(KEYFILE, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None  # Provide the password if your key is encrypted
        )
except FileNotFoundError:
    raise FileNotFoundError(f"Private key file not found at {KEYFILE}")
except Exception as e:
    raise Exception(f"Error loading private key: {str(e)}")


# Get series information for KXHIGHNY
url = "https://api.elections.kalshi.com/trade-api/v2/series/KXHIGHNY"
response = requests.get(url)
series_data = response.json()

print(f"Series Title: {series_data['series']['title']}")
print(f"Frequency: {series_data['series']['frequency']}")
print(f"Category: {series_data['series']['category']}")

# Get all markets for the KXHIGHNY series
markets_url = f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXHIGHNY&status=open"
markets_response = requests.get(markets_url)
markets_data = markets_response.json()

print(f"\nActive markets in KXHIGHNY series:")
for market in markets_data['markets']:
    print(f"- {market['ticker']}: {market['title']}")
    print(f"  Event: {market['event_ticker']}")
    print(f"  Yes Price: {market['yes_ask_dollars']}¢ | Volume: {market['volume']}")
    print()

# Get details for a specific event if you have its ticker
if markets_data['markets']:
    # Let's get details for the first market's event
    event_ticker = markets_data['markets'][0]['event_ticker']
    event_url = f"https://api.elections.kalshi.com/trade-api/v2/events/{event_ticker}"
    event_response = requests.get(event_url)
    event_data = event_response.json()

    print(f"Event Details:")
    print(f"Title: {event_data['event']['title']}")
    print(f"Category: {event_data['event']['category']}")

# Get orderbook for a specific market
# Replace with an actual market ticker from the markets list
market_ticker = markets_data['markets'][0]['ticker']
orderbook_url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook"

orderbook_response = requests.get(orderbook_url)
orderbook_data = orderbook_response.json()

print(f"\nOrderbook for {market_ticker}:")

max_count = 0
top_k = 5

yes_contract_exist, no_contract_exist = orderbook_data['orderbook']['yes']!=None, orderbook_data['orderbook']['no']!=None
print("YES BIDS:")
if yes_contract_exist:
    for bid in orderbook_data['orderbook']['yes']:  # Show top k
        print(f"  Price: {bid[0]}¢, Quantity: {bid[1]}")
        max_count += 1
        if max_count == top_k:
            break
else:
    print(f"  Price: None¢, Quantity: None")

print("\nNO BIDS:")
if no_contract_exist:
    for bid in orderbook_data['orderbook']['no']:  # Show top k
        print(f"  Price: {bid[0]}¢, Quantity: {bid[1]}")
        max_count += 1
        if max_count == top_k:
            break
else:
    print(f"  Price: None¢, Quantity: None")

# Initialize the HTTP client
client = KalshiHttpClient(
    key_id=KEYID,
    private_key=private_key,
    environment=env
)

# Get account balance
balance = client.get_balance()
print("Balance:", balance)

# Place a buy order for 1 YES contract at 1 cent
order_data = {
    "ticker": market_ticker,
    "action": "buy",
    "side": "yes",
    "count": 1,
    "type": "limit",
    "yes_price": 1,
    "client_order_id": str(uuid.uuid4())  # Unique ID for deduplication
}

# Actually placing the order
response = client.post('/trade-api/v2/portfolio/orders', order_data)
print(response)

#Delete the order
order_id = response['order']['order_id']
response = client.delete(f'/trade-api/v2/portfolio/orders/{order_id}')
print(response)