from btcpay import BTCPayClient
import configparser

main_config = configparser.ConfigParser()
main_config.read('config.ini')

btcpay_config = main_config['btcpay']

ltcpay_client = BTCPayClient(
    host=btcpay_config['url'],
    pem=btcpay_config['pemltc'],
    tokens={'merchant': btcpay_config['ltc_token']}
)

btcpay_client = BTCPayClient(
    host=btcpay_config['url'],
    pem=btcpay_config['pembtc'],
    tokens={'merchant': btcpay_config['btc_token']}
)


def genInvoice(type, callbacks, amount=0.00000001, description='no description'):
    if type == 'btc':
        invoice = btcpay_client.create_invoice({"price": amount, "currency": "BTC", "notificationURL": callbacks, "fullNotifications": True, "buyer": {"name": '123'}, "itemDesc": description}, btcpay_config['btc_token'])
    elif type == 'ltc':
        invoice = ltcpay_client.create_invoice({"price": amount, "currency": "LTC", "notificationURL": callbacks, "fullNotifications": True, "buyer": {"name": '123'}, "itemDesc": description}, btcpay_config['ltc_token'])

    return invoice
