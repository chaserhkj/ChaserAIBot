#!/usr/bin/env python3

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def logged(func):
    def logged_func(*argl, **argd):
        logging.getLogger().debug("Entering: " + func.__name__)
        try:
            res = func(*argl, **argd)
        except Exception as e:
            if "update" in argd:
                update = argd["update"]
            else:
                update = argl[1]
            update.message.reply_text("Exception: {}".format(str(e)))
            raise e
        logging.getLogger().debug("Exiting: " + func.__name__)
        return res

    return logged_func


config_path = "config.yaml"
config = {}
import yaml, os
with open(config_path, "r") as f:
    config = yaml.load(f)
tg_key = config["apikey"]
import telegram
from telegram.ext import Updater, CommandHandler
from io import BytesIO
from telegram import InputFile
import pytimeparse
import requests
tenorkey = config["tenorkey"]
res = requests.get("https://api.tenor.com/v1/anonid", params={"key": tenorkey})
anonid = res.json()["anon_id"]
updater = Updater(tg_key, workers=16)
queue = updater.job_queue

group_config = config["groups"]
reset_events = {}
unpin_events = {}
result_cache = {}
gif_cache = {}


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
        update.message.reply_text(
            "Delayed reset is enabled for this group.\n\nTitle would be reset to {} after {} seconds.\n".
            format(reset_title, delay))


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
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReply this command to the image that you wish to set as the group picture.\n"
        )
        return
    if len(msg.photo) == 0:
        update.message.reply_text("Picture not found.\n")
        return
    gid = update.message.chat.id
    pic = msg.photo[-1].file_id
    buf = BytesIO()
    f = bot.get_file(pic)
    f.download(out=buf)
    buf.seek(0)
    bot.set_chat_photo(chat_id=gid, photo=buf)


@check_group
@logged
def pin(bot, update, args):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the message you wish to pin.\n/pin [time to pin]\n"
        )
    gid = update.message.chat.id
    mid = msg.message_id
    force_notify = check_config(gid, "force_notify")
    disable_notify = not bool(force_notify)
    bot.pin_chat_message(
        chat_id=gid, message_id=mid, disable_notification=disable_notify)

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


def sendGIF(bot, cid, keyword, anime=True):
    if anime:
        keyword = "anime {}".format(keyword)
    if not cid in gif_cache:
        gif_cache[cid] = set()
    if not cid in result_cache:
        result_cache[cid] = {}
    while True:
        if not keyword in result_cache[cid]:
            res = requests.get(
                "https://api.tenor.com/v1/random",
                params={
                    "key": tenorkey,
                    "anon_id": anonid,
                    "q": keyword,
                    "safesearch": "moderate",
                    "limit": 20
                })
            result_cache[cid][keyword] = iter(res.json()["results"])

            def result_ttl(bot, job):
                del result_cache[cid][keyword]

            queue.run_once(result_ttl, 600)
        for result in result_cache[cid][keyword]:
            url = result["media"][0]["gif"]["url"]
            if not url in gif_cache[cid]:
                gif_cache[cid].add(url)

                def remove_cache(bot, job):
                    gif_cache[cid].remove(url)

                queue.run_once(remove_cache, 1800)
                bot.sendChatAction(
                    chat_id=cid, action=telegram.ChatAction.UPLOAD_PHOTO)
                bot.sendDocument(chat_id=cid, document=url, timeout=60)
                return
        del result_cache[cid][keyword]


def action_gen(keyword, reply_text, mention_text, anime=True):
    def action(bot, update):
        msg = update.message.reply_to_message
        cid = update.message.chat.id
        sendGIF(bot, cid, keyword, anime)
        if msg == None:
            update.message.reply_text(reply_text)
            return
        user = update.message.from_user
        msg.reply_text(
            "[{} {}](tg://user?id={}) {}".format(
                user.first_name, user.last_name, user.id, mention_text),
            parse_mode="Markdown")

    return logged(action)


@check_group
@logged
def unpin(bot, update):
    gid = update.message.chat.id
    bot.unpin_chat_message(chat_id=gid)
    if gid in unpin_events:
        unpin_events[gid].schedule_removal()
        del unpin_events[gid]


@logged
def list_cmd(bot, update):
    help_txt = \
"""List of non-action commands:
/start     : Grant permission for individual user
/getgid    : Show GID of current group chat
/settitle  : Set group chat title
/resettitle: Reset group chat title to default
/setpic    : Set group chat picture
/pin       : Pin message
/unpin     : Unpin pinned message
/actions   : Show action commands
/help      : Show non-action commands"""
    update.message.reply_text(help_txt)


@logged
def list_act(bot, update):
    if "actions" in config:
        act_txt = "\n".join("/{}".format(i) for i in config["actions"])
        act_txt = "List of action commands:\n" + act_txt
    else:
        act_txt = "No action command defined"
    update.message.reply_text(act_txt)


updater.dispatcher.add_handler(CommandHandler("start", start))
updater.dispatcher.add_handler(CommandHandler("getgid", getgid))
updater.dispatcher.add_handler(
    CommandHandler("settitle", settitle, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("resettitle", resettitle))
updater.dispatcher.add_handler(CommandHandler("setpic", setpic))
updater.dispatcher.add_handler(CommandHandler("pin", pin, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("unpin", unpin))
updater.dispatcher.add_handler(CommandHandler("help", list_cmd))
updater.dispatcher.add_handler(CommandHandler("actions", list_act))

if "actions" in config:
    actions = config["actions"]
    for key in actions:
        fact = action_gen(**actions[key])
        updater.dispatcher.add_handler(CommandHandler(key, fact))

updater.start_webhook(listen='127.0.0.1', port=9990, url_path=tg_key)
updater.bot.set_webhook(url='https://tgbot.chaserhkj.me/ai/' + tg_key)
updater.idle()
