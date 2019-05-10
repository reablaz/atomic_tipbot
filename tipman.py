# -*- coding: utf-8 -*-

from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, RegexHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
import telegram
from matrix import MatrixEngine
from btpayserver import genInvoice

import logging
import configparser
import datetime
import pymongo
import hashlib, binascii
import requests
import os
import time
import json
import re
import random, string
import threading


main_config = configparser.ConfigParser()
main_config.read('config.ini')

dbclient = pymongo.MongoClient('localhost')
mongo_db = "tipdb"
mongo = dbclient[mongo_db]

botconfig = main_config['telegram']

teletoken = botconfig['token']

updater = Updater(teletoken)
dispatcher = updater.dispatcher

loglevel = "DEBUG"
logpath = "bot.log"
if loglevel == "DEBUG":
    logging.basicConfig(filename=logpath, level=logging.DEBUG, format='%(asctime)s %(message)s')
elif loglevel == "INFO":
    logging.basicConfig(filename=logpath, level=logging.INFO, format='%(asctime)s %(message)s')
else:
    logging.basicConfig(filename=logpath, level=logging.WARNING, format='%(asctime)s %(message)s')

mx = MatrixEngine()

def load_dirty_json(dirty_json):
    regex_replace = [(r"([ \{,:\[])(u)?'([^']+)'", r'\1"\3"'), (r" False([, \}\]])", r' false\1'), (r" True([, \}\]])", r' true\1')]
    for r, s in regex_replace:
        dirty_json = re.sub(r, s, dirty_json)
    clean_json = json.loads(dirty_json)
    return clean_json

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


def ex_user(userid, platform="telegram"):
    ex_user = mongo.users.find_one({"platform": platform, "user": userid})

    if ex_user:
        return ex_user
        pass
    else:
        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        dk = hashlib.pbkdf2_hmac('sha256', str.encode(str(userid)), str.encode(dtime), 100000)
        userhash = binascii.hexlify(dk).decode()
        userdata = {"created_date": dtime,
                    "platform": 'telegram',
                    "userhash": userhash,
                    "balance": 0,
                    "user": userid
                    }
        recordID = mongo.users.insert_one(userdata)
        mx.sendmsg(str(userid) + ': created' + "\n\n" + str(userdata))
        return userdata

def start(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg( str(userid) + ': started TG bot')
    userdata = ex_user(userid, 'telegram')
    update.message.reply_text('Welcome to the Atomic TipBot! /help for list of commands')


def balance(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg( str(userid) + ': checked balance')
    username = update.message.from_user.username
    userdata = ex_user(userid, 'telegram')
    vouchers = mongo.vouchers.find({"to": username})
    count = 0
    sum = 0
    for v in vouchers:
        count += 1
        sum += v['amount']
    if count > 0:
        bot.send_message(chat_id=userid, text='You have ' + str(count) + ' vouchers to redeem. use /claim command')
    balance = userdata['balance']
    update.message.reply_text('Your balance is: ' + str(int(balance)) + ' satoshis')


def claim(bot, update):
    userid = update.message.from_user.id
    username = update.message.from_user.username
    mx.sendmsg( str(userid) + ': claimed funds as ' + username)
    userdata = ex_user(userid, 'telegram')
    vouchers = mongo.vouchers.find({"to": username})
    balance = userdata['balance']
    count = 0
    sum = 0
    for v in vouchers:
        count += 1
        mx.sendmsg('redeem ' + str(v['code']))
        sum += v['amount']
        mongo.vouchers.delete_one({"_id": v['_id']})
        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        v.pop("_id", None)
        v['redeemed'] = dtime
        mongo.voucher_archive.insert_one(v)
    update_balance(userid,balance+sum)
    update.message.reply_text(str(count) + ' vouchers redeemed for ' + str(sum) + ' satoshi in total')


def userrank(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg( str(userid) + ': checked rank')
    userdata = ex_user(userid, 'telegram')
    balance = userdata['balance']

    userlist = mongo.users.find({"platform": 'telegram'}).sort("balance",pymongo.DESCENDING).limit(10)

    msglist = list()
    place = 0
    for user in userlist:
        place += 1
        #mx.sendmsg(str(user))
        if user['balance'] > 0:
            username = str(user['user'])[:3] +'-'+ str(user['user'])[-3:]
            if place <= 3:
                msglist.append('<b>'+ str(place) + '. ' + username + '</b>: <i>' + str(int(user['balance'])) + '</i>')
            else:
                msglist.append(str(place) + '. ' + username + ': <i>' + str(int(user['balance'])) + '</i>')

    msg = "\n".join(msglist)
    myuser = str(userid)[:3] + '-' + str(userid)[-3:]
    update.message.reply_text("Top 10 users: \n\n" + msg + "\n\nYour ("+myuser+") balance: " + str(int(balance)), parse_mode=telegram.ParseMode.HTML)


def history(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg( str(userid) + ': asks for history')
    update.message.reply_text('Sorry this feature is under development :)', parse_mode=telegram.ParseMode.HTML)


def help(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg( str(userid) + ': asks for help')
    update.message.reply_text("<b>Send tip in a group chat:</b>\nreply any user message in group including <b>tip!xxx</b> - where xxx is amount you wish to send", parse_mode=telegram.ParseMode.HTML)
    time.sleep(3)
    bot.send_photo(userid, photo="https://myhost.org/static/chat.png", caption='send tip')
    time.sleep(1)
    bot.send_photo(userid, photo="https://myhost.org/static/confirm.png", caption='and you will get a confirmation')
    time.sleep(2)
    price_get = requests.get('https://www.bitstamp.net/api/v2/ticker/btcusd')
    if price_get.status_code == 200:
        price1ksat = str(round(float(price_get.json()['last'])/100000, 2))
    else:
        price1ksat = '0.06'
    bot.send_message(chat_id=userid,
                     text="<b>Wallet commands:</b>\n/deposit for top-ups\n/send to withdraw\n/balance to check your balance\n/history show transaction history\n\n<b>LApps:</b>\n/send2phone +118767854 1000 <i>send satoshi to number by sat2.io</i>\n/send2telegram @username 1000 <i> send satoshis to known telegram user</i>\n/paylink 10000 <i>request payment link for sharing</i>\n/bet 1000 <i>[up|down|same] [minute|hour|day|month] Bet on BTC price</i>\n/sendsms +118767854 hello, lightning! <i>send text message to number via lnsms.world</i>\n\n<b>Misc:</b>\n/top show user rank\n\n<b>What is 'satoshi'?</b>\n<a href=\"https://en.wikipedia.org/wiki/Satoshi_Nakamoto\">Satoshi</a> is a creator of Bitcoin and <a href=\"https://en.bitcoin.it/wiki/Satoshi_(unit)\">currently the smallest unit of the bitcoin currency</a>. Price of 1000 satoshis now is about $" + price1ksat + " (USD) \n\n<b>Have a problem or suggestion?</b>\n<a href=\"https://t.me/joinchat/B9nfbhWuDDPTPUcagWAm1g\">Contact bot community</a>", parse_mode=telegram.ParseMode.HTML)

def receive(bot, update):
    query = update.callback_query
    userid = query.message.chat_id
    payment_type = query['data'].replace('receive_', '')
    bot.edit_message_text(chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                        text='generating address, please wait.. *tip: address valid for 15 minutes')

def deposit(bot, update):
    #query = update.callback_query
    bot.send_message(chat_id=update.message.chat_id,
                        text=deposit_amount_menu_message(),
                        reply_markup=deposit_amount_menu_keyboard())

    userid = update.message.from_user.id


def deposit_amount(bot, update):
    query = update.callback_query
    bot.edit_message_text(chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                          text='Okay, almost done! Now generating invoice..')
    query = update.callback_query
    userid = update.callback_query.message.chat_id


    amount = int(query['data'].replace('deposit_', ''))

    amount_btc = 0.00000001 * amount

    bot.send_photo(chat_id=userid, photo="https://myhost.org/static/payment_select.png", caption="*Tip! you can change payment method on invoice page")

    invoice = genInvoice('btc', 'https://cb.yaya.cf/tips', amount=amount_btc, description=str(userid) + ' top-up')
    invoice_link = invoice['url']

    str_amount_btc = '%.8f' % amount_btc

    ### LOG invoice
    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')

    invoice_data = {"timestamp": dtime,
                    "platform": 'telegram',
                    "user": userid,
                    "invoice_id": invoice['id'],
                    "invoice_data": invoice,
                    "amount": amount
                    }

    recordID = mongo.invoices.insert_one(invoice_data)

    bot.send_message(chat_id=userid,text='Your invoice for ' + str(amount) + ' Satoshi [' + str_amount_btc +' BTC]:' + "\n\n" + invoice_link)

    mx.sendmsg(str(userid) + ' received invoice ' + invoice_link + str(amount))



def withdraw(bot, update):
    userid = update.message.from_user.id
    mx.sendmsg(str(userid) + ': withdraw')
    update.message.reply_text("Send me image of QR code or plain-text invoice [BTC or LTC].\n\nFor best UX only ⚡Lightning withdrawals are available now. If you would like receive your funds on-chain, <a href=\"https://t.me/joinchat/B9nfbhWuDDPTPUcagWAm1g\">contact us</a>", parse_mode=telegram.ParseMode.HTML)


def send2phone(bot, update, args):
    userid = update.message.from_user.id
    try:
        phone = args[0].replace('+', '')
        amount = int(args[1])
        if amount < 1000:
            update.message.reply_text("min. amount 1000 satoshi")
            return False
    except Exception as e:
        update.message.reply_text("invalid number or amount. Command format to send 10000 satoshi to +371 24948044: /send2phone +37124948044 10000")
    update.message.reply_text("Sending to " + str(phone) + " via sat2.io")
    send_req = requests.get('https://sat2.io/send/'+phone+'/'+str(amount))
    if send_req.status_code == 200:
        ln_inv = re.search('((lnbc|lnltc)[0-9a-z]*)', send_req.text)
        if ln_inv:
            plain_invoice = ln_inv.group(1)
            if pay_invoice(plain_invoice, userid):
                settled = False
                retry = 0
                while not settled:
                    check_req = requests.get('https://sat2.io/lookupInvoice/'+plain_invoice)
                    if check_req.status_code == 200:
                        status = check_req.json()['status']
                        if status == 'settled':
                            settled=True
                        else:
                            retry += 1
                    time.sleep(2)
                    if retry > 30:
                        mx.sendmsg(str(userid) + ': send2phone limit 30 retries to get invoice data for ' + plain_invoice)
                        bot.send_message(chat_id=userid, text="Unable to check that " + str(phone) + " received message")
                        return False
    else:
        bot.send_message(chat_id=userid, text="problem with sat2.io, try again later")
    mx.sendmsg(str(userid) + ': send2phone ' + str(phone) + ' ' + str(amount))
    bot.send_message(chat_id=userid, text="Sent to " + str(phone))

def sendsms(bot, update, args):

    userid = update.message.from_user.id
    try:
        phone = args[0]
        cntr = 0
        text = ''
        for arg in args:
            if cntr > 0:
                text = text + str(arg) + ' '
            cntr += 1
    except Exception as e:
        update.message.reply_text("invalid command parameters. Command format to send 'hello world' to +371 24948044: /sendsms +37124948044 hello world")

    update.message.reply_text("Sending to " + str(phone) + " [via lnsms.world]: " + text)

    payload = {
        'number': phone,
        'text': text,
        'force_unicode': 0
    }

    send_req = requests.post('https://lnsms.world/invoice', data=payload)

    if send_req.status_code == 201:
        #mx.sendmsg(send_req.text)

        plain_invoice = str(send_req.text)
        print(plain_invoice)
        invoice_info_request = requests.post('http://192.168.43.190:5000/invoiceinfo', data={"bolt": plain_invoice},
                                             auth=('ohr7zoh8Ogei7ze', 'Ophu0shohX3zie4'))
        if invoice_info_request.status_code == 200:
            invoice_info = invoice_info_request.json()
            try:
                invoice_id = invoice_info['payment_hash']
                #print('sms id: ' + invoice_id)
                #print('info: \n' + str(invoice_info))
            except KeyError as e:
                return False
        else:
            mx.sendmsg('Error contacting paylightning.py over RESTAPI to get invoice data: error ' + str(
                invoice_info_request.status_code))
            return False


        if pay_invoice(plain_invoice, userid):
            wait_req = requests.get('https://lnsms.world/invoice/'+invoice_id+'/wait')
            if wait_req.status_code==202:
                mx.sendmsg(str(userid) + ': sendsms paid ' + plain_invoice + ' and sent sms to ' + str(phone))
                bot.send_message(chat_id=userid, text="Sent to " + str(phone))
            else:
                bot.send_message(chat_id=userid, text="there was a problem to send sms to " + str(phone))
                mx.sendmsg(str(userid) + ': sendsms paid ' + plain_invoice + ' BUT NOT SENT TO ' + str(phone) + ' | code: ' + str(wait_req.status_code))
    else:
        bot.send_message(chat_id=userid, text="your number incorrect or problem with lnsms.world, in that case try again later")
        mx.sendmsg(str(userid) + ': sendsms FAILED ' + str(phone) + ' ' + str(text))


def paylink(bot, update, args):
    userid = update.message.from_user.id
    try:
        amount = int(args[0])
    except Exception as e:
        update.message.reply_text("invalid amount. Command format to request 1000 satoshi: /paylink 1000")
        return False

    amount_btc = 0.00000001 * amount
    update.message.reply_text('Generating invoice..')
    invoice = genInvoice('btc', 'https://cb.yaya.cf/tips', amount=amount_btc, description=str(userid)[:3] +'-'+ str(userid)[-3:] + ' paylink')
    invoice_link = invoice['url']

    ### LOG invoice
    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')

    invoice_data = {"timestamp": dtime,
                    "platform": 'telegram',
                    "user": userid,
                    "invoice_id": invoice['id'],
                    "invoice_data": invoice,
                    "amount": amount
                    }

    recordID = mongo.invoices.insert_one(invoice_data)

    str_amount_btc = '%.8f' % amount_btc

    mx.sendmsg(str(userid) + ': paylink ' + str(userid) + ' : ' + invoice_link)
    bot.send_message(chat_id=userid, text='Invoice for ' + str(
        amount) + ' Satoshi [' + str_amount_btc + ' BTC]\n\nMessage to forward:')
    time.sleep(1)
    bot.send_message(chat_id=userid, text='Send me bitcoin using this link: '+invoice_link)


def charge_user(userid, amount, destination):
    userdata = mongo.users.find_one({"platform": 'telegram', "user": userid})
    if userdata:
        cur_balance = userdata['balance']
        newbalance = cur_balance - amount
        if newbalance >= 0 and amount > 0:
            mongo.users.update_one(
                {"user": userid, "platform": 'telegram'},
                {
                    "$set":
                        {
                            "balance": newbalance
                        }
                }
            )
            dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
            tx_data = {
                'timestamp': dtime,
                'event': 'withdraw',
                'platform': 'telegram',
                'from': userid,
                'to': destination,
                'amount': amount
            }
            mongo.txs.insert_one(tx_data)
            mx.sendmsg(
                str(userid) + ' balance updated from ' + str(cur_balance) + ' to ' + str(newbalance) + '[-' + str(
                    amount) + ' sats]')
            time.sleep(1)
            return True
        else:
            return False
    else:
        return False

def make_bet(userid, amount, trend, set_time, chat_id, msg_id):
    bot = telegram.Bot(teletoken)

    if amount < 1 or set_time not in ['minute', 'hour', 'day', 'month'] and trend not in ['up', 'down', 'same']:
        bot.send_message(chat_id=userid, text='Wrong command usage. /bet 1000 <i>[up|down|same] [minute|hour|day|month]</i>', parse_mode=telegram.ParseMode.HTML)
        return False

    if charge_user(userid, amount, 'bet_'+trend+'_'+set_time):
        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        if set_time == 'minute':
            coef = 1.01
            tdelta = datetime.timedelta(minutes=1)
        elif set_time == 'hour':
            coef = 1.13
            tdelta = datetime.timedelta(hours=1)
        elif set_time == 'day':
            coef = 1.19
            tdelta = datetime.timedelta(days=1)
        elif set_time == 'month':
            coef = 1.23
            tdelta = datetime.timedelta(days=30)

        win_amount = int(round(amount*coef))

        price_get = requests.get('https://www.bitstamp.net/api/v2/ticker/btcusd')
        if price_get.status_code == 200:
            price = int(round(float(price_get.json()['last'])))
        else:
            bot.send_message(chat_id=userid, text='error occured getting rate @ bitstamp, try again later')
            return False

        recorddate = datetime.datetime.strptime(dtime, '%Y-%m-%d %H:%M:%S')

        unixtime_exp = recorddate + tdelta

        bet_data = {
            'timestamp': dtime,
            'exp_timestamp': datetime.datetime.strftime(unixtime_exp, '%Y-%m-%d %H:%M:%S'),
            'unixtime_exp': unixtime_exp,
            'event': 'bet',
            'chat_id': chat_id,
            'msg_id': msg_id,
            'trend': trend,
            'price': price,
            'status': 'new',
            'timeout': set_time,
            'platform': 'telegram',
            'userid': userid,
            'to': 'bet_'+trend+'_'+set_time,
            'amount': amount,
            'win': win_amount
        }
        mongo.bets.insert_one(bet_data)

        bot.send_message(chat_id=chat_id, text="Your "+str(int(amount))+"sat bet is accepted, hodler! You will receive " + str(int(win_amount)) + " if bitcoin price go " + trend + " from " + str(price) + "@Bitstamp in a " + set_time, reply_to_message_id=msg_id)

        if trend == 'up':
            bot.send_animation(chat_id=userid, animation="https://i.imgur.com/AcItxdr.gif", caption='Good luck!')
        elif trend == 'down':
            bot.send_animation(chat_id=userid, animation="https://i.imgur.com/wJYyCSw.gif", caption='Good luck!')
        elif trend == 'same':
            bot.send_animation(chat_id=userid, animation="https://i.imgur.com/VbC8kNM.gif", caption='Good luck!')
        return True
    else:
        mx.sendmsg(str(userid) + ' not enought funds? problem for bet [' + 'bet_'+trend+'_'+set_time + ']')
        bot.send_animation(userid, animation="https://i.imgur.com/UY8I7ow.gif",
                           caption="Not enought funds. Would you like to top-up? /deposit")
        return False


def bet_menu(bot, update):
    query = update.callback_query
    # bot.edit_message_text(chat_id=query.message.chat_id,
    #                    message_id=query.message.message_id,
    #                      text='Okay, almost done! Now generating invoice..')
    query = update.callback_query
    chat_id = update.callback_query.message.chat_id
    userid = update.callback_query.from_user.id
    msgid = update.callback_query.message.message_id

    trend = query['data'].replace('bet_', '')

    amount = 3000

    return make_bet(userid, amount, trend, 'hour', chat_id, msgid)


def bet(bot, update, args):
    userid = update.message.from_user.id
    chat_id = update.message.chat.id
    msgid = update.message.message_id
    mx.sendmsg(str(userid) + ': bet')

    #/bet 100 [up|down|same] [minute|hour|day|month]
    ex_user(userid)

    try:
        amount = int(args[0])
        trend = str(args[1])
        set_time = str(args[2])
    except Exception as e:
        bot.send_message(chat_id=update.message.chat_id,
                         text=bet_menu_message(),
                         reply_markup=bet_menu_keyboard())
        return False

    return make_bet(userid, amount, trend, set_time, chat_id, msgid)


def send2telegram(bot, update, args):
    userid = update.message.from_user.id
    mx.sendmsg(str(userid) + ': send2telegram')

    def genvoucher(userid, amount, receiver):
        dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        userdata = mongo.users.find_one({"platform": 'telegram', "user": userid})
        voucher = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        voucher_data = {
            'timestamp': dtime,
            'code': voucher,
            'event': 'send2tele',
            'platform': 'telegram',
            'from': userid,
            'to': receiver.replace('@', ''),
            'amount': amount
        }
        mongo.vouchers.insert_one(voucher_data)
        return voucher

    try:
        receiver = args[0]
        amount = int(args[1])
        if charge_user(userid, amount, receiver):
        #bot.send_animation(receiver, animation="https://myhost.org/static/duck.gif", caption='You received ' + str(amount) + ' satoshis!')
            myvoucher = genvoucher(userid, amount, receiver)
        #bot.send_message(chat_id=receiver, text='To claim funds use this code \n\n' + myvoucher)
            mx.sendmsg(str(userid) + ' generated voucher ['+myvoucher+'] for ' + receiver)
            update.message.reply_text("Funds reserved for " + receiver + ", now he needs send /claim command to @atomic_tipbot")
        else:
            myvoucher = 'empty'
            mx.sendmsg(str(userid) + ' not enought funds for voucher [' + myvoucher + '] for ' + receiver)
            bot.send_animation(userid, animation="https://i.imgur.com/UY8I7ow.gif", caption="Not enought funds. Would you like to top-up? /deposit")
    except Exception as e:
        mx.sendmsg('failed to send funds to telegram: ' + str(e))
        update.message.reply_text("failed to send funds. Command format to send 10000 to @btcShadow: /send2telegram @btcShadow 10000")


def sendtip(bot, update):
    userid = update.message.from_user.id
    message = update.message
    chat_type = update.message.chat.type
    try:
        chat_title = update.message.chat.title
    except Exception as e:
        chat_title = ''
    reply = load_dirty_json(str(message['reply_to_message']))
    text = update.message.text
    #room_id = mx.create_room('TG-'+str(userid))

    try:
        to_username = reply['from']['username']
    except KeyError:
        to_username = '-'

    try:
        to_fn = reply['from']['first_name']
    except KeyError:
        to_fn = '-'

    receiver = {
        "id": reply['from']['id'],
        "username": to_username,
        "name": to_fn
    }

    try:
        from_username = message.from_user.username
    except Exception:
        from_username = '-'

    try:
        from_fn = message.from_user.first_name
    except Exception:
        from_fn = '-'

    sender = {
        "id": message.from_user.id,
        "username": from_username,
        "name": from_fn
    }

    m = re.search('[Tt]ip!([0-9]*)', text)
    if m:
        sender_dbdata = ex_user(sender['id'], platform='telegram')
        receiver_dbdata = ex_user(receiver['id'], platform='telegram')
        tip_amount = int(m.group(1))

        mx.sendmsg('tip found: ' + str(tip_amount) + ' from ' + str(sender['id']) + ' to ' + str(receiver['id']))

        if sender_dbdata['balance'] >= tip_amount and sender_dbdata['balance'] > 0:
            sender_newbalance = sender_dbdata['balance'] - tip_amount
            receiver_newbalance = receiver_dbdata['balance'] + tip_amount
            dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
            tip_data = {
                'timestamp': dtime,
                'event': 'tip',
                'platform': 'telegram',
                'sender_hash': sender_dbdata['userhash'],
                'receiver_hash': receiver_dbdata['userhash'],
                'amount_satoshi': tip_amount,
                'sender_balance': int(sender_newbalance),
                'receiver_balance': int(receiver_newbalance),
                'sender': sender['id'],
                'receiver': receiver['id']
            }
            tx_data = {
                'timestamp': dtime,
                'event': 'tip',
                'platform': 'telegram',
                'from': sender['id'],
                'to': receiver['id'],
                'amount_satoshi': tip_amount
            }
            #print(tip_data)
            mongo.tips.insert_one(tip_data)
            mongo.txs.insert_one(tx_data)

            update_balance(sender['id'], sender_newbalance, 'telegram')
            update_balance(receiver['id'], receiver_newbalance, 'telegram')
            bot.send_animation(sender['id'], animation="https://i.imgur.com/CCqdiZZ.gif",
                              caption='You sent ' + str(int(tip_amount)) + ' satoshis to ' + receiver['name'] + '(' + receiver['username'] + ')')
            bot.send_animation(receiver['id'], animation="https://i.imgur.com/U7VL2CV.gif", caption='You received ' + str(int(tip_amount)) + ' satoshis')
            mx.sendmsg('succesfull tip of '+str(tip_amount)+' from ' + str(tx_data['from']) + ' to ' +str(tx_data['to']))
        else:
            bot.send_animation(sender['id'], animation="https://i.imgur.com/UY8I7ow.gif", caption='Not enought funds to send tip. use /deposit')

            mx.sendmsg(
                'failed tip of ' + str(tip_amount) + ' from ' + str(sender['id']) + ' to ' + str(receiver['id']))

    else:
        mx.sendmsg('tip not found in '+ chat_type + ' ' + chat_title + ' reply message')

    #mx.sendmsg(str(userid) + "(TG-tip): \n\n" + str(sender) + "\n" + str(receiver))

def pay_invoice(dirty_text, userid):
    ln_inv = re.search('((lnbc|lnltc)[0-9a-z]*)', dirty_text)
    if ln_inv:
        plain_invoice = ln_inv.group(1)
        mx.sendmsg(str(userid) + ' wants to pay: ' + plain_invoice)
        payload = {
            "user": userid,
            "bolt": plain_invoice
        }
        pay_response = requests.post('http://192.168.43.190:5000/pay', data=payload,
                                     auth=('ohr7zoh8Ogei7ze', 'Ophu0shohX3zie4'))
        if pay_response.status_code == 200:
            invoice_info_payload = {
                "bolt": plain_invoice
            }
            invoice_info_request = requests.post('http://192.168.43.190:5000/invoiceinfo', data=invoice_info_payload,
                                     auth=('ohr7zoh8Ogei7ze', 'Ophu0shohX3zie4'))
            if invoice_info_request.status_code == 200:
                invoice_info = invoice_info_request.json()
                try:
                    desc = invoice_info['description']
                    amount_satoshi = int(round(invoice_info['msatoshi']/1000))
                    mx.sendmsg('User ' + str(userid) + ' paid ' + str(amount_satoshi) + ' satoshis [' + desc + '] ' + pay_response.text)
                except KeyError as e:
                    mx.sendmsg('User ' + str(userid) + ' paid ' + plain_invoice + ', but we cannot decode data ' + invoice_info_request.text)
            else:
                mx.sendmsg('Error contacting paylightning.py over RESTAPI to get invoice data: error ' + str(invoice_info_request.status_code))
            return True
        else:
            userbot = telegram.Bot(teletoken)
            userbot.send_message(userid, 'Payment server is unreachable [error ' + str(
                pay_response.status_code) + ']. Sorry for that, contact us https://t.me/joinchat/B9nfbhWuDDPTPUcagWAm1g for more details')
            mx.sendmsg( 'Payment server is unreachable [error ' + str(
                pay_response.status_code) + '].')
    else:
        # if wrong inv data do nothing
        mx.sendmsg(str(userid) + ': wrong invoice in ' + "\n\n\n" + dirty_text)
        userbot = telegram.Bot(teletoken)
        userbot.send_message(userid, 'Invoice is wrong')
    return False

def decodeimg(fpath):

    dtime_short = datetime.datetime.strftime(datetime.datetime.now(), '%Y%m%d_%H%M%S')
    file_name = dtime_short

    cvres = '/tmp/' + file_name + '_bot_image_data'
    os.system('python2.7 misc/opencv.py ' + fpath + ' 2>> misc/cv_error.log 1>> ' + cvres)
    try:
        lines = tuple(open(cvres, 'r'))
        if not lines:
            return False
    except Exception as e:
        return False

    raw = str(lines)
    mx.sendmsg('processing raw data from image data ' + raw)
    mx.sendfile(fpath)
    type_raw = re.search('Type :  ([a-z0-9A-Z]*)', raw)
    data_raw = re.search('Data :  ([a-z0-9A-Z:?=\.&]*)', raw)
    if type_raw and data_raw:
        structured_data = {
            "type": type_raw.group(1),
            "data": data_raw.group(1)
        }
        mx.sendmsg(str(structured_data))
        return structured_data
    else:
        return False

def processphoto(bot, update):
    userid = update.message.from_user.id
    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
    mx.sendmsg(str(userid) + ': image processing')

    chat_type = update.message.chat.type

    if chat_type != 'private':
        return False

    try:
        file = bot.getFile(update.message.photo[-1].file_id)
    except Exception as e:
        os.system('echo "' + dtime + 'TG fileget error" >> misc/telegram_error.log')
        print('Error on file get from telegram: ' + str(e))
        update.message.reply_text('whooops! Telegram server went offline for a while. Please re-send image')
    dtime_short = datetime.datetime.strftime(datetime.datetime.now(), '%Y%m%d_%H%M%S')
    image_name = dtime_short+'_'+str(userid)
    fpath = '/tmp/' + image_name + '_bot_image'
    file.download(custom_path=fpath)
    update.message.reply_text('processing image, please wait... if no response for some while than your image failed to decode. more info /send')
    image = decodeimg(fpath)
    userbot = telegram.Bot(teletoken)
    try:
        if image['data'] != '':
            if not pay_invoice(image['data'], userid):
                mx.sendmsg(str(userid) + ': invoice pay failed')
                userbot.send_message(userid, 'Payment failed')
            else:
                pass
                # info about succesfull payment sent from pay_invoice()
    except KeyError:
        mx.sendmsg(str(userid) + ': failed do extract data from image')
        userbot.send_message(userid, 'Cannot read image.. try again')

def processtext(bot, update):
    userid = update.message.from_user.id
    text = update.message.text
    chat_type = update.message.chat.type
    chat_id = update.message.chat.id
    usermame = update.message.from_user.username
    firstname = update.message.from_user.first_name
    #room_id = mx.create_room('TG-'+str(userid))
    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')

    msgdata = {
        "dtime": dtime,
        "platform": 'telegram',
        "first_name": firstname,
        "username": usermame,
        "from_user": userid,
        "chat_type": chat_type,
        "chat_id": chat_id,
        "text": text
    }

    if chat_type == 'private':
        if text.startswith("lnbc") or text.startswith("lnltc"):
            update.message.reply_text('detected invoice, attemp to pay now')
            if not pay_invoice(text, userid):
                mx.sendmsg(str(userid) + ': invoice pay failed')
        else:
            mx.sendmsg(str(userid) + '(TG-direct-' + str(userid) + '): ' + text)
    else:
        msgdata['chat_title'] = update.message.chat.title

    mongo.messages.insert_one(msgdata)



def deposit_amount_menu_keyboard():
    keyboard = [[InlineKeyboardButton('100 Satoshi', callback_data='deposit_100')],
                [InlineKeyboardButton('1 000 Satoshi', callback_data='deposit_1000')],
                [InlineKeyboardButton('10 000 Satoshi', callback_data='deposit_10000')],
                [InlineKeyboardButton('100 000 Satoshi', callback_data='deposit_100000')]]
    return InlineKeyboardMarkup(keyboard)

def deposit_amount_menu_message():
    return 'Choose amount you want to deposit:'

def bet_menu_keyboard():
    keyboard = [[InlineKeyboardButton('Go up!', callback_data='bet_up')],
                [InlineKeyboardButton('Go down!', callback_data='bet_down')],
                [InlineKeyboardButton('Will stay same', callback_data='bet_same')]]
    return InlineKeyboardMarkup(keyboard)

def bet_menu_message():
    return 'Bet 3000 satoshi that in a hour Bitcoin price will:'


def init_tg_bot():
    usertip = MessageHandler(Filters.reply, sendtip)
    usertext = MessageHandler(Filters.text, processtext)
    userphoto = MessageHandler(Filters.photo, processphoto)

    updater.dispatcher.add_handler(CommandHandler('start', start,filters=Filters.private))
    updater.dispatcher.add_handler(CommandHandler('help', help))
    updater.dispatcher.add_handler(CommandHandler('deposit', deposit,filters=Filters.private))
    updater.dispatcher.add_handler(CommandHandler('send', withdraw,filters=Filters.private))
    updater.dispatcher.add_handler(CommandHandler('balance', balance))
    updater.dispatcher.add_handler(CommandHandler('top', userrank))
    updater.dispatcher.add_handler(CommandHandler('claim', claim))
    updater.dispatcher.add_handler(CommandHandler('bet', bet, pass_args=True))
    updater.dispatcher.add_handler(CommandHandler('send2phone', send2phone, pass_args=True))
    updater.dispatcher.add_handler(CommandHandler('send2telegram', send2telegram, pass_args=True))
    updater.dispatcher.add_handler(CommandHandler('sendsms', sendsms, pass_args=True))
    updater.dispatcher.add_handler(CommandHandler('paylink', paylink, pass_args=True))
    updater.dispatcher.add_handler(CommandHandler('history', history,filters=Filters.private))

    updater.dispatcher.add_handler(CallbackQueryHandler(receive, pattern='receive_*'))

    updater.dispatcher.add_handler(CallbackQueryHandler(deposit_amount, pattern='deposit_*'))
    updater.dispatcher.add_handler(CallbackQueryHandler(bet_menu, pattern='bet_*'))

    dispatcher.add_handler(usertip)
    dispatcher.add_handler(usertext)
    dispatcher.add_handler(userphoto)

def betcheck():
    threading.Timer(30.0, betcheck).start()

    ##check bets
    bets = mongo.bets.find({"status": 'new'}).sort("amount",pymongo.DESCENDING).limit(10)
    bot = telegram.Bot(teletoken)

    gotprice = False
    price_get = requests.get('https://www.bitstamp.net/api/v2/ticker/btcusd')
    retry = 0
    while not gotprice:
        retry += 1
        if price_get.status_code == 200:
            gotprice = True
            price = int(round(float(price_get.json()['last'])))
        else:
            mx.sendmsg('betcheck: error contacting bitstamp, try: ' + str(retry))
            print('betcheck: Could not retrieve data from exchange, re-trying: ' + str(retry))


    for bet in bets:
        now_time = datetime.datetime.now()
        bet_time = datetime.datetime.strptime(bet['timestamp'], '%Y-%m-%d %H:%M:%S')
        bet_exp = bet['unixtime_exp']

        if bet_exp < now_time:
            if bet['trend'] == 'up':
                win = (bet['price'] < price)
            elif bet['trend'] == 'down':
                win = (bet['price'] > price)
            else:
                win = (bet['price'] == price)

            if win:
                balance = ex_user(bet['userid'])['balance']
                update_balance(bet['userid'], int(balance)+int(bet['win']), 'telegram')
                bot.send_animation(chat_id=bet['userid'], animation="https://i.imgur.com/bZAS9ac.gif", caption="Congratulations! You won " + str(int(bet['win'])) + " satoshis! " + str(bet['price']) + bet['trend'] + str(price))
                bot.send_message(chat_id=bet['chat_id'], text='Someone just won ' + str(int(bet['win'])) + ' satoshis on bets!', reply_to_message_id=bet['msg_id'])
                mx.sendmsg(str(bet['userid']) + ' won bet ' + str(int(bet['win'])))
            else:
                bot.send_animation(chat_id=bet['userid'], animation="https://i.imgur.com/2bmpZsM.gif", caption="Your bet wasn't lucky one! Bet on " + str(bet['price']) + bet['trend'] + ", but price is" + str(price))
                mx.sendmsg(str(bet['userid']) + ' won  bet ' + str(int(bet['win'])) )

            mongo.bets.update_one(
                {"_id": bet['_id'], "platform": 'telegram'},
                {
                    "$set":
                        {
                            "status": 'expired'
                        }
                }
            )
        time.sleep(1)

betcheck()

init_tg_bot()
updater.start_polling()
