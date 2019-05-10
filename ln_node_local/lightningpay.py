# -*- coding: utf-8 -*-
from flask import Flask
from flask_restful import Resource, Api, reqparse, request
from flask_httpauth import HTTPBasicAuth
from lightning import LightningRpc, RpcError
import pymongo
import telegram
import time
import requests
import re
import datetime

auth = HTTPBasicAuth()
app = Flask(__name__)
api = Api(app)

USER_DATA = {
    "bAxX0zoh8ObADbAD0": "bAxX0zoh8ObADbAD0"
}

telegram_bot_token = '60423423281:Ac2lUjuOPX0NAc2lUjuOPHxpbADxhxyQc'
atomic_tipbot = '8834534558:AAc2lUt7BoPi7P3t7BoPi7P3t7BoPi7PurwOP0zEw'
telegram_bot = telegram.Bot(telegram_bot_token)
userbot = telegram.Bot(atomic_tipbot)

dbclient = pymongo.MongoClient('192.168.0.43')
mongo_db = "tipdb"
mongo = dbclient[mongo_db]

lnltc = LightningRpc("/home/ltc/.lightning/lightning-rpc")
lnbtc = LightningRpc("/home/payer/.lightning/lightning-rpc")

def sendTele(msg):
    telegram_bot.send_message(chat_id='admin_user_id', text="paylightning.py:\n " + msg)

def sendNBpic(userid, msg):
    userbot.send_animation(userid, animation="https://i.imgur.com/UY8I7ow.gif", caption=msg)


def notifyUser(userid, msg):
    userbot.send_message(chat_id=userid, text=msg, parse_mode=telegram.ParseMode.HTML)

@auth.verify_password
def verify(username, password):
    if not (username and password):
        return False
    return USER_DATA.get(username) == password

class GetInvoiceInfo(Resource):
    @auth.login_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('bolt')
        args = parser.parse_args()
        invoice = args['bolt']
        ln_inv = re.search('((lnbc|lnltc)[0-9a-z]*)', invoice)
        invoice_type = ln_inv.group(2)

        try:
            if invoice_type == 'lnbc':
                decoded = lnbtc.decodepay(invoice)
                decoded.pop("amount_msat", None)
            elif invoice_type == 'lnltc':
                decoded = lnltc.decodepay(invoice)
                decoded.pop("amount_msat", None)
            else:
                decoded = {'error': 'error'}
        except RpcError as e:
            decoded = {'error': 'error'}
            sendTele('error on getting invoice data: ' + str(e))

        return decoded

def update_balance(userid, newbalance, platform="telegram"):
    mongo.users.update_one(
        {"user": userid, "platform": platform},
        {
            "$set":
                {
                    "balance": int(newbalance)
                }
        }
    )

class NewTX(Resource):
    @auth.login_required
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('bolt')
        parser.add_argument('user')
        args = parser.parse_args()

        invoice = args['bolt']
        try:
            userid = int(args['user'])
        except Exception as e:
            resp = {
                            'status' : False,
                           'error': str(e)}
            return resp

        def handle_rpc_err(e, deal_amount=0):
            errcode = e.error['code']
            errmsg = e.error['message']

            balance = mongo.users.find_one({"platform": 'telegram', "user": userid})['balance']

            if errcode == 207:
                # if payment expired
                notifyUser(userid, 'Failed payment: ' + errmsg)
                time.sleep(2)
                sendTele(str(userid) + ' user failed to send payment: [LN errcode:' + str(errcode) + ']' + errmsg + "\n\n" + invoice)
                time.sleep(2)
                #refund user
                update_balance(userid, balance+deal_amount)
                notifyUser(userid, 'Payment canceled, refund received: ' + str(deal_amount) + ' satoshi')
            if errcode == 205:
                # if colud not find a route
                notifyUser(userid, 'Failed payment: ' + errmsg + '\nDoes receiving node has enough capacity?')
                time.sleep(2)
                sendTele(str(userid) + ' user failed to send payment: [LN errcode:' + str(errcode) + ']' + errmsg + "\n\n" + invoice)
                time.sleep(2)
                #refund user
                update_balance(userid, balance+deal_amount)
                notifyUser(userid, 'Payment canceled, refund received: ' + str(deal_amount) + ' satoshi')
            else:
                notifyUser(userid,
                           'Failed payment: ' + errmsg + "\n\nIf something went completely wrong <a href=\"https://t.me/joinchat/B9nfbhWuDDPTPUcagWAm1g\"> contact us</a>")
                time.sleep(2)
                sendTele(str(userid) + ' user failed to send payment: [LN errcode:' + str(errcode) + ']' + str(e) + "\n\n" + invoice)


        def charge_user(userid, amount, destination):
            userdata = mongo.users.find_one({"platform": 'telegram', "user": userid})
            if userdata:
                cur_balance=userdata['balance']
                newbalance=cur_balance - amount
                if newbalance >= 0:
                    update_balance(userid, newbalance)
                    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    tx_data = {
                        'timestamp': dtime,
                        'event': 'withdraw',
                        'platform': 'telegram',
                        'from': userid,
                        'to': destination,
                        'amount': amount,
                        'status': 'paid'
                    }
                    mongo.txs.insert_one(tx_data)
                    sendTele(str(userid) + ' balance updated from ' + str(cur_balance) + ' to ' + str(newbalance) + '[-'+str(amount)+' sats]')
                    time.sleep(1)
                    return True
                else:
                    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    tx_data = {
                        'timestamp': dtime,
                        'event': 'withdraw',
                        'platform': 'telegram',
                        'from': userid,
                        'to': destination,
                        'amount': amount,
                        'status': 'no funds'
                    }
                    mongo.txs.insert_one(tx_data)

                    return False
            else:
                return False


        if invoice.startswith("lnbc"):
            ex_user = mongo.users.find_one({"platform": 'telegram', "user": userid})
            try:
                invoice_data = lnbtc.decodepay(invoice)
            except RpcError as e:
                return False
            amount_satoshi = invoice_data['msatoshi'] / 1000
            if ex_user:
                if 0 < amount_satoshi < ex_user['balance']:
                    try:
                        try:
                            already_paid = False
                            pays = lnbtc.listpays(invoice)['pays']
                            for pay in pays:
                                already_paid = (pay['status'] == 'complete')
                        except RpcError as e:
                            sendTele('got listpay error: ' + str(e))
                            already_paid = False

                        if already_paid:
                            notifyUser(userid, 'You already have paid this invoice')
                            return False
                        else:
                            if charge_user(userid, amount_satoshi, invoice):
                                lnbtc.pay(invoice)
                                notifyUser(userid, 'You just paid ' + str(int(amount_satoshi)) + ' satoshis ☺')
                                return True
                            else:
                                notifyUser(userid, 'Failed to pay ' + invoice)
                                return False

                    except RpcError as e:
                        if charge_user(userid, amount_satoshi, invoice):
                            notifyUser(userid, 'You just paid ' + str(int(
                                amount_satoshi)) + ' satoshis. some error occured ☹, your payment still in transit. tx may be reverted')
                            time.sleep(1)
                            sendTele(str(userid) + ' just paid ' + str(
                                int(invoice_data['msatoshi'] / 1000)) + ' satoshis WITH ERROR RPC ('+str(e)+') - ' + invoice)
                            time.sleep(1)
                        else:
                            sendTele('AHTUNG! EXPLOIT! ON BTC')
                            time.sleep(1)
                            update_balance(userid, 0)

                        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                        tx_data = {
                            'timestamp': dtime,
                            'event': 'withdraw',
                            'platform': 'telegram',
                            'from': userid,
                            'balance_before_err': ex_user['balance'],
                            'to': invoice,
                            'status': 'RPC_ERROR',
                            'err': str(e)
                        }
                        mongo.problem_txs.insert_one(tx_data)

                        handle_rpc_err(e, amount_satoshi)
                        return False

                else:
                    sendNBpic(userid,'Not enought funds. Would you like to top-up? /deposit')
            else:
                print(str(userid) + ' user not found')
                sendTele(str(userid) + ' user not found')
                return False

        elif invoice.startswith("lnltc"):
            ex_user = mongo.users.find_one({"platform": 'telegram', "user": userid})
            try:
                invoice_data = lnltc.decodepay(invoice)
            except RpcError as e:
                return False
            amount_lites = invoice_data['msatoshi'] / 1000

            gotprice = False
            retry=0
            while not gotprice:
                retry += 1
                rawltcprice = requests.get('https://www.bitstamp.net/api/v2/ticker/ltcbtc')
                if rawltcprice.status_code == 200:
                    gotprice = True
                    ltcprice = float(rawltcprice.json()['last'])
                    amount_satoshi = amount_lites * ltcprice
                else:
                    notifyUser(userid, 'Could not retrieve data from exchange, re-trying: ' + str(retry))
                    print(str(userid) + 'Could not retrieve data from exchange, re-trying: ' + str(retry))
                    sendTele(str(userid) + 'Could not retrieve data from exchange, re-trying: ' + str(retry))
                    time.sleep(5)
            if ex_user:
                if 0 < amount_satoshi < ex_user['balance']:
                    try:
                        try:
                            already_paid = False
                            pays = lnltc.listpays(invoice)['pays']
                            for pay in pays:
                                already_paid = (pay['status'] == 'complete')
                        except RpcError as e:
                            sendTele('get listpay error: ' + str(e))
                            already_paid = False

                        if already_paid:
                            notifyUser(userid, 'You already have paid this invoice')
                            return False
                        else:
                            if charge_user(userid, amount_satoshi, invoice):
                                lnltc.pay(invoice)
                                notifyUser(userid, 'You just paid ' + str(int(amount_satoshi)) + ' satoshis ☺')
                                return True
                            else:
                                notifyUser(userid, 'Failed to pay ' + invoice)
                                return False

                    except RpcError as e:
                        if charge_user(userid, amount_satoshi, invoice):
                            notifyUser(userid, 'You just paid ' + str(int(
                                amount_satoshi)) + ' satoshis. some error occured ☹, your payment still in transit. tx may be reverted')
                            time.sleep(1)
                            sendTele(str(userid) + ' just paid ' + str(
                                int(invoice_data['msatoshi'] / 1000)) + ' satoshis WITH ERROR RPC ('+str(e)+') - ' + invoice)
                            time.sleep(1)
                        else:
                            sendTele('AHTUNG! EXPLOIT! ON LTC')
                            time.sleep(1)
                            update_balance(userid, 0)

                        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                        tx_data = {
                            'timestamp': dtime,
                            'event': 'withdraw',
                            'platform': 'telegram',
                            'from': userid,
                            'balance_before_err': ex_user['balance'],
                            'to': invoice,
                            'status': 'RPC_ERROR',
                            'err': str(e)
                        }
                        mongo.problem_txs.insert_one(tx_data)

                        handle_rpc_err(e, amount_satoshi)
                        return False

                else:
                    sendNBpic(userid, 'Not enought funds. Use /deposit')
                    return False
            else:
                print(str(userid) + ' user not found')
                sendTele(str(userid) + ' user not found')
                return False

        else:
            notifyUser(userid, 'For best UX only ⚡Lightning withdrawals are available now. If you would like receive your funds on-chain - <a href=\"https://t.me/joinchat/B9nfbhWuDDPTPUcagWAm1g\"> contact us</a>')


api.add_resource(NewTX, '/pay')
api.add_resource(GetInvoiceInfo, '/invoiceinfo')

if __name__ == '__main__':
    app.run(debug=False)

