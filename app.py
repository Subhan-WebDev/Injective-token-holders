from flask import Flask, request, render_template, jsonify, send_file
import asyncio
import csv
import os
from tqdm import tqdm
from pyinjective.async_client import AsyncClient
from pyinjective.client.model.pagination import PaginationOption
from pyinjective.core.network import Network
from grpc.aio import AioRpcError
from grpc import StatusCode

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/snapshot_page')
def snapshot_page():
    return render_template('snapshot_page.html')

@app.route('/snapshot', methods=['POST'])
def snapshot():
    token_address = request.form['token_address']
    asyncio.run(main(token_address))
    return jsonify({"status": "Data fetching initiated. Check your CSV file status."})

@app.route('/status')
def check_status():
    if os.path.exists('TokenHolder.csv'):
        return jsonify({"status": "ready"})
    else:
        return jsonify({"status": "processing"})

@app.route('/download')
def download_file():
    return send_file('TokenHolder.csv', as_attachment=True)

async def fetch_all_zigcoin_owners(denom):
    network = Network.mainnet()
    client = AsyncClient(network)
    all_owners = []
    processed_addresses = set()
    next_key = None
    total_fetched = 0
    retries = 0
    max_retries = 5

    with tqdm(desc="Fetching owners", unit="owner") as pbar:
        while True:
            pagination = PaginationOption(limit=5000)
            if next_key:
                pagination.key = next_key

            try:
                owners_response = await client.fetch_denom_owners(
                    denom=denom,
                    pagination=pagination,
                )
                retries = 0  # Reset retries on successful fetch
            except AioRpcError as e:
                if e.code() == StatusCode.UNAVAILABLE:
                    if retries < max_retries:
                        retries += 1
                        sleep_time = 2 ** retries
                        print(f"Server unavailable, retrying in {sleep_time} seconds...")
                        await asyncio.sleep(sleep_time)
                        continue
                    else:
                        print("Max retries reached. Exiting.")
                        break
                else:
                    raise e

            denom_owners = owners_response.get('denomOwners', [])
            if not denom_owners:
                print("No more owners found.")
                break

            new_owners = [owner for owner in denom_owners if owner['address'] not in processed_addresses]
            all_owners.extend(new_owners)
            fetched_count = len(new_owners)
            total_fetched += fetched_count

            print(f"Fetched {fetched_count} new owners. Total so far: {total_fetched}")
            pbar.update(fetched_count)
            processed_addresses.update(owner['address'] for owner in new_owners)

            new_next_key = owners_response['pagination'].get('nextKey')
            if next_key == new_next_key:
                print("Pagination key did not advance, stopping.")
                break
            next_key = new_next_key
            if not next_key:
                pbar.total = total_fetched
                pbar.close()
                break

    return all_owners

async def write_to_csv(denom_owners, denom):
    if denom.startswith("peggy") or denom.startswith("inj"):
        conversion_factor = 10**18
    else:
        conversion_factor = 10**6

    for owner in denom_owners:
        owner['balance']['amount'] = round(float(owner['balance']['amount']) / conversion_factor)

    with open('TokenHolder.csv', 'w', newline='') as csvfile:
        fieldnames = ['address', 'amount']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{'address': owner['address'], 'amount': owner['balance']['amount']} for owner in denom_owners])

    print(f"Data has been written to TokenHolder.csv (total {len(denom_owners)} owners)")

async def main(denom):
    denom_owners = await fetch_all_zigcoin_owners(denom)
    await write_to_csv(denom_owners, denom)

if __name__ == '__main__':
    app.run(debug=True)
