from matrix_client.client import MatrixClient
from matrix_client.api import MatrixRequestError, MatrixHttpApi
from requests.exceptions import MissingSchema
import configparser
import datetime
import sys
import time
import random
import string
import pymongo

mxconfig = configparser.ConfigParser()
mxconfig.read('config.ini')

botconfig = mxconfig['matrix']

bothost = botconfig['host']
botuser = botconfig['username']
botpwd = botconfig['password']
botroom = botconfig['test_room']

ebuser = '@eb:matrix.org'

dbclient = pymongo.MongoClient('localhost')
mongo_db = "smdb"
matrix_mongo = dbclient[mongo_db]

def randomString(stringLength=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength))


class MatrixEngine(object):
    chatapi = ''
    chatclient = ''
    chattoken = ''
    listener_thread_id = 0
    new_msg_queue = []
    new_msg_senders = []

    def __init__(self, host=bothost, user=botuser, pwd=botpwd, room=botroom):
        print("Logging to matrix server...")
        self.chatclient = MatrixClient(host)
        try:
            self.chattoken = self.chatclient.login(username=user, password=pwd, sync=True)
        except MatrixRequestError as e:
            print(e)
            if e.code == 403:
                print("Bad username or password.")
                sys.exit(4)
            else:
                print("Check your sever details are correct.")
                sys.exit(2)
        except MissingSchema as e:
            print("Bad URL format.")
            print(e)
            sys.exit(3)
        self.chatapi = MatrixHttpApi(host, self.chattoken)
        print("Login OK")

        ### handle messages
        print("Setting up listener")
        try:
            room = self.chatclient.join_room(room)
        except MatrixRequestError as e:
            print(e)
            if e.code == 400:
                print("Room ID/Alias in the wrong format")
                sys.exit(11)
            else:
                print("Couldn't find room.")
                sys.exit(12)

        room.add_listener(self.on_message)
        self.listener_thread_id = self.chatclient.start_listener_thread()
        print('Listener set.. OK!')

    def sendmsg(self, msg, chatid=botroom):
        room = self.chatclient.join_room(chatid)
        response = self.chatapi.send_message(chatid, msg)

    def sendhtml(self, msg, chatid=botroom):
        room = self.chatclient.join_room(chatid)
        room.send_html(msg)

    def create_room(self, alias):
        ex_room = matrix_mongo.matrix_chats.find_one({"alias": alias})
        if ex_room:
            room_id = ex_room['room_id']
            room = self.chatclient.join_room(room_id)
            room.invite_user(ebuser)
        else:
            try:
                aldt = datetime.datetime.strftime(datetime.datetime.now(), '%Y%m%d%H%M%S')
                new_room = self.chatclient.create_room(alias=alias+"_"+aldt, is_public=False, invitees=[ebuser])
                room_id = new_room.room_id
                dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                chatdata = {"created_date": dtime,
                         "alias": alias,
                         "room_alias": alias+"_"+aldt,
                         "room_id": room_id,
                         "room_data": room
                         }

                recordID = matrix_mongo.matrix_chats.insert_one(chatdata)
            except MatrixRequestError as e:
                print(str(e))

        return room_id

    def sendfile(self, filename, chatid=botroom):
        room = self.chatclient.join_room(chatid)

        with open(filename, 'rb') as datafile:
            data = datafile.read()
            uri = self.chatclient.upload(content=data, content_type='image/jpg')
            print(uri)
            filedate = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
            room.send_image(uri, filedate+'_'+filename.replace('/', '_')+'.jpg')

    def on_message(self, room, event):
        try:
            # Called when a message is recieved.
            if event['type'] == "m.room.member":
                if event['membership'] == "join":
                    # print("{0} joined".format(event['content']['displayname']))
                    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    print(dtime + " new user joined to the room ")
            elif event['type'] == "m.room.message":
                if event['content']['msgtype'] == "m.text":
                    # print("{0}: {1}".format(event['sender'], event['content']['body']))
                    dtime = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    print(dtime + "|  '" + event['content']['body'] + "' msg received from " + event['sender'])
                    if event['sender'] != "@mybot:matrix.org":
                        self.new_msg_senders.append(event['sender'])
                        self.new_msg_queue.append(event['content']['body'])
            else:
                print('new event in room:' + event['type'])
        except Exception as e:
            print('error @ on_message: ' + str(e))

    def parsemsg(self):
        for i in range(len(self.new_msg_queue)):
            origMsg = self.new_msg_queue[i]
            sender = self.new_msg_senders[i]

            msg = origMsg.lower()

            print("PARSER:  '" + origMsg + "' msg received from " + sender)

            def doshit():
                print('shit done')

            if msg == "test":
                doshit()
            elif msg == "msg":
                sendmsg("your msg responded!")
            elif msg == "html":
                sendhtml("your <b>html</b>  message <h1>responded</h1>!")
            else:
                print("message not understood")

            self.new_msg_queue.remove(origMsg)
            self.new_msg_senders.remove(sender)
