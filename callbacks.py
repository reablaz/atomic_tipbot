from flask import Flask
from flask_restful import Resource, Api, reqparse, request
import telegram
import time
import pymongo
import datetime

from btcpay import BTCPayClient
import btcpay.crypto

app = Flask(__name__)
api = Api(app)

blazhbot_token = '604622781:AAHxpbADxX0N5DWkNTrJoGc2lUjuOPhxyQc'
atomic_tipbot = '887263958:AAHzL_ycuxBKkIt7BorwXOpmfxPi7P30zEw'

bot = telegram.Bot(blazhbot_token)

userbot = telegram.Bot(atomic_tipbot)

dbclient = pymongo.MongoClient('localhost')
mongo_db = "tipdb"
mongo = dbclient[mongo_db]

### BTCPay
btcpay_client = BTCPayClient(
    host='https://btcpayjungle.com',
    pem='''
-----BEGIN EC PRIVATE KEY-----
pemPEMpemPEMpemPEMpemPEMpemPEMpemPEMpemPEM
pemPEMpemPEMpemPEMpemPEMpemPEMpemPEMpemPEM
pemPEMpemPEMpemPEMpemPEMpemPEMpemPEMpemPEM
pemPEMpemPEMpemPEMpemPEMpemPEMpemPEMpemPEM
-----END EC PRIVATE KEY-----
''',
    tokens={'merchant': '7NyxUT6ybc6ybcmM1bJmT66ybcmM1bJybcmT2U'}
)


def sendTele(msg):
    bot.send_message(chat_id='admin_user_id', text=msg)

def answerUser(userid, msg):
    userbot.send_message(userid, msg)

def answer_newBalance(userid, msg):
    userbot.send_animation(userid, animation="https://myhost.org/static/duck.gif", caption=msg)

def prepareMsg(jsonmsg):
    status = jsonmsg['status']
    amount = jsonmsg['price']
    cur = jsonmsg['currency']
    paymentid = jsonmsg['id']
    msg = status + ' payment! Amount: ' + str(amount) + ' ' + cur + '; Payment ID: ' + paymentid
    return msg

class ProcessTips(Resource):
    def post(self):
        pdata = request.get_json(silent=True)
        if pdata != "null":
            try:
                amount = 0
                invoice_id = pdata['id']

                existing_invoice = mongo.invoices.find_one({"invoice_id": invoice_id})
                userid = existing_invoice['user']
                user = mongo.users.find_one({"platform": 'telegram', "user": userid})
                balance = user['balance']

                data = btcpay_client.get_invoice(invoice_id)

                #sendTele(invoice_id)
                amount = round(float(data['btcPrice'])-float(data['btcDue']), 8)
                amount_sat = amount * 100000000

                #print(data)
                if pdata['status'] == 'paid':
                    answerUser(userid, str(amount_sat) + ' Satoshi received (wait for confirmation if used on-chain tx)')
                    time.sleep(1)
                elif pdata['status'] == 'complete' and data['status'] == 'complete':
                    new_balance = balance + amount_sat
                    mongo.users.update_one(
                        {"user": userid, "platform": 'telegram'},
                        {
                            "$set":
                                {
                                    "balance": new_balance
                                }
                        }
                    )
                    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    tx_data = {
                        'timestamp': dtime,
                        'event': 'deposit',
                        'platform': 'telegram',
                        'from': invoice_id,
                        'to': userid,
                        'amount_satoshi': amount_sat
                    }
                    mongo.txs.insert_one(tx_data)
                    answer_newBalance(userid, str(int(amount_sat)) + ' Satoshis added to your balance. Your balance: ' + str(int(new_balance)))
                    time.sleep(1)
                    sendTele(str(userid) + " added "+str(amount_sat)+" Satoshis [" + '%.8f' % amount + ' BTC]')

                elif pdata['status'] != 'complete' and pdata['status'] != 'paid':
                    time.sleep(1)
                    sendTele('new status for ['+invoice_id+' id] for user ' + str(userid) + ': ' + data['status'])
            except Exception as e:
                time.sleep(1)
                sendTele('error on prepareMsg: ' + str(e))

#            sent = False
#            while not sent:
#                try:
#                    sendTele(prepareMsg(pdata))
#                    sent=True
#                except Exception as e:
#                    print('failed to send msg to telegram')
#                    time.sleep(10)
        else:
            print('no data')


class CallBack(Resource):
    def post(self):
        pdata = request.get_json(silent=True)
        if pdata != "null":
            try:
                print(prepareMsg(pdata))
            except Exception as e:
                sendTele('error on prepareMsg')
            sent = False
            while not sent:
                try:
                    sendTele(prepareMsg(pdata))
                    sent=True
                except Exception as e:
                    print('failed to send msg to telegram')
                    time.sleep(10)
        else:
            print('no data')

api.add_resource(CallBack, '/')
api.add_resource(ProcessTips, '/tips')

if __name__ == '__main__':
    app.run(debug=False)