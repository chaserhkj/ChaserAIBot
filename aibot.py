#!/usr/bin/env python3

import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def logged(func):
    def logged_func(*argl, **argd):
        logging.getLogger().debug("Entering: " + func.__name__)
        res = func(*argl, **argd)
        logging.getLogger().debug("Exiting: " + func.__name__)
        return res
    return logged_func


config_path = "config.yaml"
config = {}
import yaml, os
with open(config_path, "r") as f:
    config = yaml.load(f)
tg_key = config["apikey"]
from telegram.ext import Updater, CommandHandler
from io import BytesIO
from telegram import InputFile
import pytimeparse
updater = Updater(tg_key, workers = 16)
queue = updater.job_queue

group_config = config["groups"]
reset_events = {}
unpin_events = {}

def check_group(func):
    def new_func(*arg, **argd):
        update = argd.get("update", arg[1])
        chat = update.message.chat
        if chat.type == chat.GROUP or chat.type == chat.SUPERGROUP:
            func(*arg, **argd)
        else:
            update.message.reply_text("Current chat is not a group\n")
    return new_func

def check_config(gid, key):
    if gid in group_config and key in group_config[gid]:
        return group_config[gid][key]
    else:
        return None

@logged
def start(bot, update):
    update.message.reply_text("Hi, how are you doing today?\n")


@logged
@check_group
def getgid(bot, update):
    chat = update.message.chat
    update.message.reply_text("Group ID is: {}\n".format(chat.id, chat.GROUP))

@check_group
@logged
def settitle(bot, update, args):
    chat = update.message.chat
    if len(args) == 0:
        update.message.reply_text("Usage: /settitle <title>\n")
        return
    old_title = chat.title
    gid = chat.id
    title = " ".join(args)
    prefix = check_config(gid, "title_prefix")
    title = "{} {}".format(prefix, title) if prefix != None else title
    bot.set_chat_title(chat_id=gid, title=title)

    delay = check_config(gid, "title_reset_delay")
    if delay != None:
        if gid in reset_events:
            reset_events[gid].schedule_removal()
        reset_title = old_title if prefix == None else prefix
        def reset(bot, job):
            bot.set_chat_title(chat_id=gid, title=reset_title)
            del reset_events[gid]
        event = queue.run_once(reset, delay)
        reset_events[gid] = event
        update.message.reply_text("Delayed reset is enabled for this group.\n\nTitle would be reset to {} after {} seconds.\n".format(reset_title, delay))



@check_group
@logged
def resettitle(bot, update):
    gid = update.message.chat.id
    prefix = check_config(gid, "title_prefix")
    if prefix == None:
        update.message.reply_text("No title prefix setup!")
        return
    bot.set_chat_title(chat_id=gid, title=prefix)
    if gid in reset_events:
        reset_events[gid].schedule_removal()
        del reset_events[gid]

@check_group
@logged
def setpic(bot, update):
    update.message.reply_text("Not Implemented")
    return
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text("Usage:\n\nReply this command to the image that you wish to set as the group picture.\n")
        return
    if len(msg.photo) == 0:
        update.message.reply_text("Picture not found.\n")
        return
    gid = update.message.chat.id
    pic = msg.photo[-1].file_id
    buf = BytesIO()
    f = bot.get_file(pic)
    f.download(out = buf)
    buf.seek(0)
    inputfile = InputFile({"photo": buf})
    bot.set_chat_photo(chat_id=gid, photo=inputfile.data)

@check_group
@logged
def pin(bot, update, args):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text("Usage:\n\nReplying to the message you wish to pin.\n/pin [time to pin]\n")
    gid = update.message.chat.id
    mid = msg.message_id
    force_notify = check_config(gid, "force_notify")
    disable_notify = not bool(force_notify)
    bot.pin_chat_message(chat_id=gid, message_id=mid, disable_notification = disable_notify)

    if len(args) == 0:
        return
    delay = pytimeparse.parse(args[0])
    if gid in unpin_events:
        unpin_events[gid].schedule_removal()
    def unpin(bot, job):
        bot.unpin_chat_message(chat_id=gid)
        del unpin_events[gid]
    event = queue.run_once(unpin, delay)
    unpin_events[gid] = event

@check_group
@logged
def unpin(bot, update):
    gid = update.message.chat.id
    bot.unpin_chat_message(chat_id=gid)
    if gid in unpin_events:
        unpin_events[gid].schedule_removal()
        del unpin_events[gid]



updater.dispatcher.add_handler(CommandHandler("start", start))
updater.dispatcher.add_handler(CommandHandler("getgid", getgid))
updater.dispatcher.add_handler(CommandHandler("settitle", settitle, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("resettitle", resettitle))
updater.dispatcher.add_handler(CommandHandler("setpic", setpic))
updater.dispatcher.add_handler(CommandHandler("pin", pin, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("unpin", unpin))

updater.start_polling()
updater.idle()

