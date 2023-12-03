
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
import requests
import threading
import time
from datetime import datetime, timedelta
from threading import Timer
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from threading import Timer
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///transactions.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_address = db.Column(db.String(42), nullable=False)
    eth_balance = db.Column(db.Float, nullable=False)
    token = db.Column(db.String(42), nullable=False)
    dextools_link = db.Column(db.String(300), nullable=False)
    etherscan_link = db.Column(db.String(300), nullable=False)
    transaction_hash = db.Column(db.String(66), unique=True, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (f"<Transaction hash={self.transaction_hash}, "
                f"from={self.from_address}, "
                f"eth_balance={self.eth_balance}, "
                f"token={self.token}, "
                f"timestamp={self.timestamp}>")


ETHERSCAN_API_KEY = 'YGYGHTNB2PPH9M243WE446Y53W6Y6EJX61'
UNISWAP_ROUTER_ADDRESS = '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D'
API_URL = "https://api.etherscan.io/api"

# Uniswap method IDs and their corresponding ABI signatures
UNISWAP_METHODS = {
    '0xb6f9de95', # swapExactETHForTokensSupportingFeeOnTransferTokens
    '0x7ff36ab5', # swapExactETHForTokens
    '0x791ac947', # swapExactTokensForETHSupportingFeeOnTransferTokens
    '0x4a25d94a', # swapTokensForExactETH
    '0x3037a87c', # swapExactTokensForTokensSupportingFeeOnTransferTokens
    '0xfb3bdb41', # swapETHForExactTokens
    # '0x3593564c', # execute
}

def fetch_transactions_in_block(block_number='latest'):
    params = {
        'module': 'proxy',
        'action': 'eth_getBlockByNumber',
        'tag': block_number,
        'boolean': 'true',
        'apikey': ETHERSCAN_API_KEY
    }
    response = requests.get(API_URL, params=params)
    if response.status_code == 200:
        block_data = response.json()
        return block_data.get('result', {}).get('transactions', [])
    else:
        print(f"Error fetching block: {response.status_code}")
        return []

def extract_data_from_input(input_data):
    method_id = input_data[:10]

    # Define a dictionary mapping method IDs to their token address position
    method_positions = {
        '0xb6f9de95': 418,  # swapExactETHForTokensSupportingFeeOnTransferTokens
        '0x7ff36ab5': 418,  # swapExactETHForTokens
        '0x791ac947': 418,  # swapExactTokensForETHSupportingFeeOnTransferTokens
        '0x4a25d94a': 418,  # swapTokensForExactETH
        '0x3037a87c': 418,  # swapExactTokensForTokensSupportingFeeOnTransferTokens
        '0xfb3bdb41': 418,  # swapETHForExactTokens
    }

    if method_id in method_positions:
        token_address_pos = method_positions[method_id]
        token_address = '0x' + input_data[token_address_pos:token_address_pos + 40]
        return token_address

    return None

def get_eth_balance(address):
    url = f"https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest&apikey={ETHERSCAN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        balance_wei = int(data['result'])
        balance_eth = balance_wei / 1e18
        return balance_eth
    else:
        print(f"Error fetching balance for {address}: {response.status_code}")
        return 0


def process_transactions(transactions):
    for tx in transactions:
        method_id = tx.get('input')[:10]
        if method_id in UNISWAP_METHODS:
            token_address = extract_data_from_input(tx.get('input'))
            eth_balance = get_eth_balance(tx['from'])
            if token_address:
                existing_tx = Transaction.query.filter_by(transaction_hash=tx['hash']).first()
                if existing_tx:
                    continue  # Skip adding if this transaction already exists

                dextools_link = f"https://www.dextools.io/app/uniswap/pair-explorer/{token_address}"
                etherscan_link = f"https://etherscan.io/tx/{tx['hash']}"
                new_tx = Transaction(
                    from_address=tx['from'],
                    eth_balance=eth_balance,
                    token=token_address,
                    dextools_link=dextools_link,
                    etherscan_link=etherscan_link,
                    transaction_hash=tx['hash'],
                    timestamp=datetime.utcnow()  # Set timestamp here
                )

                db.session.add(new_tx)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()



def fetch_and_process():
    with app.app_context():
        while True:
            transactions = fetch_transactions_in_block()
            process_transactions(transactions)
            time.sleep(15)

@app.route('/')
def index():
    transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    return render_template('index.html', transactions=transactions)

@app.route('/transactions')
def get_transactions():
    transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    return jsonify([
        {
            "from_address": tx.from_address,
            "eth_balance": tx.eth_balance,
            "token": tx.token,
            "dextools_link": tx.dextools_link,
            "etherscan_link": tx.etherscan_link,
            "timestamp": tx.timestamp.isoformat()
        }
        for tx in transactions
    ])

@app.route('/aggregate-token-data')
def aggregate_token_data():
    try:
        token_address = request.args.get('tokenAddress')
        print(f"Token Address: {token_address}")  # Debugging

        transactions = Transaction.query.filter_by(token=token_address).all()
        print(f"Transactions Found: {len(transactions)}")  # Debugging

        transaction_count = len(transactions)
        total_eth_balance = sum(tx.eth_balance for tx in transactions if tx.eth_balance is not None)
        print(f"Total ETH Balance: {total_eth_balance}")  # Debugging

        return jsonify({
            'transactionCount': transaction_count,
            'totalEthBalance': total_eth_balance
        })
    except Exception as e:
        print(f"Error in aggregate_token_data: {e}")  # Debugging
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    threading.Thread(target=fetch_and_process, daemon=True).start()
    app.run(debug=True)


