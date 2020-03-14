#!/usr/bin/env python3

import os
import yaml
from wallstreet import Stock
import random
import shelve
import json
from pprint import pformat
import requests
import datetime
import pytimeparse
from telegram import InputFile
from io import BytesIO
from telegram.ext import Updater, CommandHandler, Filters, MessageHandler, RegexHandler, CallbackQueryHandler
import telegram
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
            update.message.reply_text("{}: {}".format(str(type(e)), str(e)))
            raise e
        logging.getLogger().debug("Exiting: " + func.__name__)
        return res

    return logged_func


config_path = "config.yaml"
action_path = "actions.yaml"
config = {}
with open(config_path, "r") as f:
    config = yaml.load(f)
with open(action_path, "r") as f:
    actions = yaml.load(f)["actions"]
tg_key = config["apikey"]
tenorkey = config["tenorkey"]
res = requests.get("https://api.tenor.com/v1/anonid", params={"key": tenorkey})
anonid = res.json()["anon_id"]
updater = Updater(tg_key, workers=16)
queue = updater.job_queue
db = shelve.open("data.db")
if not "sticker_response" in db:
    db["sticker_response"] = {}
if not "text_response" in db:
    db["text_response"] = {}
if not "user_ids" in db:
    db["user_ids"] = {}
if not "quotes" in db:
    db["quotes"] = {}

group_config = config["groups"]
reset_events = {}
unpin_events = {}
result_cache = {}
gif_cache = {}
regex_handlers = {}
owner = config["owner"]
response_cd = set()
quote_moderator = [owner]
if "quote_moderator" in config:
    quote_moderator.extend(config["quote_moderator"])


def check_owner(func):
    def new_func(*arg, **argd):
        update = argd.get("update", arg[1])
        if update.message.from_user.id != owner:
            update.message.reply_text("呃……这个我只能听我家主人说了算")
            update.message.reply_sticker("CAADBQADJwEAAgsiPA5l3hNO8JyiPAI")
        else:
            func(*arg, **argd)

    return new_func


def check_restrict(func):
    def new_func(*arg, **argd):
        update = argd.get("update", arg[1])
        bot = argd.get("bot", arg[0])
        uid = update.message.from_user.id
        member = bot.get_chat_member(update.message.chat.id, uid)
        if not (member.status == 'creator' or member.can_restrict_members):
            update.message.reply_text("你没有管理小黑屋的权限哦")
            update.message.chat.send_sticker(
                sticker="CAADBQADJwIAAgsiPA7OflnL6kErDgI")
        else:
            func(*arg, **argd)

    return new_func


def check_admin(func):
    def new_func(*arg, **argd):
        update = argd.get("update", arg[1])
        bot = argd.get("bot", arg[0])
        uid = update.message.from_user.id
        member = bot.get_chat_member(update.message.chat.id, uid)
        if not (member.status == 'creator' or member.status == 'administrator'):
            update.message.reply_text("你没有管理员权限哦")
            update.message.chat.send_sticker(
                sticker="CAADBQADJwIAAgsiPA7OflnL6kErDgI")
        else:
            func(*arg, **argd)

    return new_func


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
    update.message.reply_text("嗨多磨～")


@logged
@check_group
def getgid(bot, update):
    chat = update.message.chat
    update.message.reply_text("Group ID is: {}\n".format(chat.id))


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
        update.message.reply_text("呼姆，这个群设置了默认群名呢……我会在{}秒后将群名重置为{}的……".format(
            delay, reset_title))


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
        return
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


def sendGIF(bot, cid, keyword, anime=True, reply_msg=None):
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
                if reply_msg == None:
                    bot.sendDocument(chat_id=cid, document=url, timeout=60)
                else:
                    bot.sendDocument(
                        chat_id=cid,
                        document=url,
                        timeout=60,
                        reply_to_message_id=reply_msg.message_id)
                return
        del result_cache[cid][keyword]


def action_gen(keyword, reply_text, mention_text, self_text, anime=True):
    def action(bot, update):
        msg = update.message.reply_to_message
        cid = update.message.chat.id
        if msg == None:
            sendGIF(bot, cid, keyword, anime, update.message)
            update.message.reply_text(reply_text)
            return
        target_id = msg.from_user.id
        self_id = bot.get_me().id
        user = update.message.from_user
        sendGIF(bot, cid, keyword, anime, msg)
        if target_id == self_id:
            update.message.reply_text(self_text)
            return
        msg.reply_text(
            "[{} {}](tg://user?id={}) {}".format(
                "" if user.first_name == None else user.first_name, ""
                if user.last_name == None else user.last_name, user.id,
                mention_text),
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


unban_events = {}


@check_group
@check_restrict
@logged
def ban(bot, update, args):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the user you wish to ban.\n/ban [Ban Time]\n"
        )
        return
    if len(args) == 0:
        ban_time = None
    else:
        ban_time = args[0]
    ban_user(bot, update.message.chat, msg.from_user, ban_time)


def ban_user(bot, chat, user, ban_time=None):
    member = chat.get_member(user.id)
    if member.status == 'creator' or member.status == 'administrator':
        chat.send_message("呃呃，我没有处理管理员的权限啊！")
        chat.send_sticker(
            sticker="CAADBQADJwEAAgsiPA5l3hNO8JyiPAI")
        return
    gid = chat.id
    uid = user.id
    bot.restrict_chat_member(
        gid,
        uid,
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        timeout=10)
    chat.send_message("{} 跟我乖乖到小黑屋里走一趟吧, 刑期: {}".format(user.mention_markdown(), "无限" if ban_time == None else ban_time),
                      parse_mode="Markdown")
    chat.send_sticker(sticker="CAADBQADJwIAAgsiPA7OflnL6kErDgI")
    if ban_time == None:
        return
    delay = pytimeparse.parse(ban_time)
    if not gid in unban_events:
        unban_events[gid] = {}
    if uid in unban_events[gid]:
        unban_events[gid][uid].schedule_removal()

    def timed_unban(bot, job):
        bot.restrict_chat_member(
            gid,
            uid,
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            timeout=10)
        chat.send_message(
            text="{}刑满释放了！".format(user.mention_markdown()),
            parse_mode="Markdown")
        chat.send_sticker(
            sticker="CAADBQADbAEAAgsiPA5ZwMJd8rkuxgI")
        del unban_events[gid][uid]

    event = queue.run_once(timed_unban, delay)
    unban_events[gid][uid] = event


@check_group
@check_restrict
@logged
def banpic(bot, update, args):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the user you wish to ban.\n/banpic [Ban Time]\n"
        )
        return
    member = update.message.chat.get_member(msg.from_user.id)
    if member.status == 'creator' or member.status == 'administrator':
        update.message.reply_text("呃呃，我没有处理管理员的权限啊！")
        update.message.chat.send_sticker(
            sticker="CAADBQADJwEAAgsiPA5l3hNO8JyiPAI")
        return
    user = member.user
    gid = update.message.chat.id
    uid = user.id
    bot.restrict_chat_member(
        gid,
        uid,
        can_send_messages=True,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        timeout=10)
    update.message.reply_text(
        "[{} {}](tg://user?id={}) {}".format(
            "" if user.first_name == None else user.first_name, ""
            if user.last_name == None else user.last_name, user.id,
            "把头伸过来，我给你加个不能发图的buff"),
        parse_mode="Markdown")
    update.message.chat.send_sticker(sticker="CAADBQADJwIAAgsiPA7OflnL6kErDgI")
    if len(args) == 0:
        return
    delay = pytimeparse.parse(args[0])
    if not gid in unban_events:
        unban_events[gid] = {}
    if uid in unban_events[gid]:
        unban_events[gid][uid].schedule_removal()

    def timed_unban(bot, job):
        bot.restrict_chat_member(
            gid,
            uid,
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            timeout=10)
        update.message.chat.send_text(
            "[{} {}](tg://user?id={}) {}".format(
                "" if user.first_name == None else user.first_name, "" if
                user.last_name == None else user.last_name, user.id, "刑满释放了！"),
            parse_mode="Markdown")
        update.message.chat.send_sticker(
            sticker="CAADBQADbAEAAgsiPA5ZwMJd8rkuxgI")
        del unban_events[gid][uid]

    event = queue.run_once(timed_unban, delay)
    unban_events[gid][uid] = event


@check_group
@check_restrict
@logged
def unban(bot, update):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the user you wish to unban.\n/unban\n")
        return
    member = update.message.chat.get_member(msg.from_user.id)
    if member.status != 'restricted':
        update.message.reply_text("呃呃，他就不在小黑屋里面啊")
        update.message.chat.send_sticker(
            sticker="CAADBQADJwEAAgsiPA5l3hNO8JyiPAI")
        return
    user = member.user
    gid = update.message.chat.id
    uid = user.id
    bot.restrict_chat_member(
        gid,
        uid,
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        timeout=10)
    update.message.reply_text(
        "[{} {}](tg://user?id={}) {}".format(
            "" if user.first_name == None else user.first_name, "" if
            user.last_name == None else user.last_name, user.id, "从小黑屋里放出来了！"),
        parse_mode="Markdown")
    update.message.chat.send_sticker(sticker="CAADBQADbAEAAgsiPA5ZwMJd8rkuxgI")
    if not gid in unban_events:
        unban_events[gid] = {}
    if uid in unban_events[gid]:
        unban_events[gid][uid].schedule_removal()
        del unban_events[gid][uid]


@logged
def list_cmd(bot, update):
    help_txt = \
        """List of non-action commands:
/start     : Grant permission for individual user
/getgid    : Show GID of current group chat
/getsid    : Show id of sticker
/getuid    : Show your user ID
/settitle  : Set group chat title
/resettitle: Reset group chat title to default
/setpic    : Set group chat picture
/pin       : Pin message
/unpin     : Unpin pinned message
/postit    : Post the message to the group channel
/quote     : Print a random quote
/addquote  : Add a message to the quotes
/rmquote   : Remove a message from the quotes
/lsquotes  : Show quotes list
/actions   : Show action commands
/setsres   : Set up sticker response
/delsres   : Delete sticker response
/lssres    : List sticker response
/settres   : Set up text response
/deltres   : Delete text response
/lstres    : List text response
/shows     : Show sticker by id
/ban       : Ban user to send messages for a certain period of time
/banpic    : Ban user to send pictures for a certain period of time
/unban     : Unban user from previous bans
/duel      : Invite other player to a duel
/help      : Show non-action commands"""
    update.message.reply_text(help_txt)


@logged
def list_act(bot, update):
    if len(actions) != 0:
        act_txt = "\n".join("/{}".format(i) for i in actions)
        act_txt = "List of action commands:\n" + act_txt
    else:
        act_txt = "No action command defined"
    update.message.reply_text(act_txt)


@logged
def getsid(bot, update):
    msg = update.message.reply_to_message
    if msg == None or msg.sticker == None:
        update.message.reply_text("Usage:\nReply to sticker")
        return
    update.message.reply_text("Sticker ID:{}".format(msg.sticker.file_id))


@logged
def getuid(bot, update):
    user = update.message.from_user
    update.message.reply_text("Your User ID:{}".format(user.id))


def respond(bot, update, response):
    chance = response[0]
    cd = response[1]
    rtype = response[2].lower()
    content = response[3]
    sig = (rtype, content)
    if sig in response_cd:
        return
    if cd > 0:
        response_cd.add(sig)

        def reset_cd(bot, job):
            response_cd.remove(sig)

        queue.run_once(reset_cd, cd)
    if 0 < chance and chance < 1:
        if random.uniform(0, 1) > chance:
            return
    if rtype == "text":
        update.message.reply_text(content, parse_mode="Markdown")
    elif rtype == "sticker":
        update.message.reply_sticker(content)
    elif rtype == "gif":
        sendGIF(bot, update.message.chat.id, content, False, update.message)


@logged
def sticker_response(bot, update):
    log_user_id(bot, update)
    sid = update.message.sticker.file_id
    if not sid in db["sticker_response"]:
        return
    respond(bot, update, db["sticker_response"][sid])


@check_owner
@logged
def setsres(bot, update, args):
    if len(args) < 5:
        update.message.reply_text(
            "Usage: /setsres <sticker_id> <chance> <cooldown> <response_type> <response_content>"
        )
        return
    sid = args[0]
    chance = float(args[1])
    cd = int(args[2])
    rtype = args[3]
    content = " ".join(args[4:])
    sr = db["sticker_response"]
    sr[sid] = (chance, cd, rtype, content)
    db["sticker_response"] = sr
    db.sync()
    update.message.reply_text("Entry updated")


@check_owner
@logged
def delsres(bot, update, args):
    if len(args) < 1:
        update.message.reply_text("Usage: /delsres <sticker_id>")
        return
    sid = args[0]
    if sid in db["sticker_response"]:
        sr = db["sticker_response"]
        del sr[sid]
        db["sticker_response"] = sr
        db.sync()
    update.message.reply_text("Entry deleted")


@logged
def lssres(bot, update):
    update.message.reply_text(pformat(db["sticker_response"]))


def generate_reghandler(response):
    def handler(bot, update):
        respond(bot, update, response)

    return handler


@check_owner
@logged
def settres(bot, update, args):
    if len(args) < 5:
        update.message.reply_text(
            "Usage: /settres <regex> <chance> <cooldown> <response_type> <response_content> "
        )
        return
    regex = args[0]
    chance = float(args[1])
    cd = int(args[2])
    rtype = args[3]
    content = " ".join(args[4:])
    tr = db["text_response"]
    tr[regex] = (chance, cd, rtype, content)
    db["text_response"] = tr
    db.sync()
    h = RegexHandler(regex, generate_reghandler(tr[regex]))
    if regex in regex_handlers:
        updater.dispatcher.remove_handler(regex_handlers[regex])
    regex_handlers[regex] = h
    updater.dispatcher.add_handler(h)
    update.message.reply_text("Entry updated")


@check_owner
@logged
def deltres(bot, update, args):
    if len(args) < 1:
        update.message.reply_text("Usage: /deltres <regex>")
        return
    regex = args[0]
    if regex in db["text_response"]:
        tr = db["text_response"]
        del tr[regex]
        db["text_response"] = tr
        db.sync()
    if regex in regex_handlers:
        updater.dispatcher.remove_handler(regex_handlers[regex])
        del regex_handlers[regex]
    update.message.reply_text("Entry deleted")


@logged
def lstres(bot, update):
    update.message.reply_text(pformat(db["text_response"]))


@logged
def shows(bot, update, args):
    if len(args) < 1:
        update.message.reply_text("Usage: /shows <sticker_id>")
        return
    update.message.reply_sticker(args[0])


@logged
def stock(bot, update, args):
    if len(args) < 1:
        update.message.reply_text("Usage: /stock <ticker>")
        return
    ticker = args[0]
    stk = Stock(ticker, source="yahoo")
    name = stk.name
    name = name.replace("&amp;", "&")
    update.message.reply_text("{}({}) 最近交易价格为{:.2f}, 最近交易日变动{:.2f}({:.1f}%)".format(
        name, stk.ticker, stk.price, stk.change, stk.cp))


count_watches = config["watches"]["count"]
old_member_count = {}


def watch_count(gid, bot):
    try:
        count = bot.get_chat_members_count(gid)
    except telegram.TelegramError:
        return
    if not gid in old_member_count:
        old_member_count[gid] = count
    if count < old_member_count[gid]:
        chat = bot.get_chat(gid)
        # Notify owner
        bot.send_message(owner, "{} member(s) have left group {}".format(
            old_member_count[gid] - count, chat.title))
        # Notify group if set
        if count_watches[gid]["notify"]:
            bot.send_message(gid, "{} member(s) have left".format(
                old_member_count[gid] - count))
        # Notify extra target if set
        notify_target = check_config(gid, "notify_watches_to")
        if notify_target:
            bot.send_message(notify_target, "{} member(s) have left group {}".format(
                old_member_count[gid] - count, chat.title))
    old_member_count[gid] = count


def callback_poll_count(bot, job):
    for gid in count_watches:
        watch_count(gid, bot)


member_watches = config["watches"]["member"]
old_status = {}


def watch_member(gid, uid, bot):
    key = "{}_{}".format(gid, uid)
    try:
        member = bot.get_chat_member(gid, uid)
    except telegram.TelegramError:
        return
    if member == None:
        return
    user = member.user
    status = member.status
    if not key in old_status:
        old_status[key] = status
    if status == 'left' and status != old_status[key]:
        chat = bot.get_chat(gid)
        # Notify Owner
        bot.send_message(owner, "{} have left group {}".format(
            user.full_name, chat.title))
        if member_watches[gid][uid]["message"]:
            bot.send_message(owner, member_watches[gid][uid]["message"])
        # Notify Group if set
        if member_watches[gid][uid]["notify"]:
            bot.send_message(gid, "{} have left".format(user.full_name))
            if member_watches[gid][uid]["message"]:
                bot.send_message(gid, member_watches[gid][uid]["message"])
        # Notify extra target if set
        notify_target = check_config(gid, "notify_watches_to")
        if notify_target:
            bot.send_message(notify_target, "{} have left group {}".format(
                user.full_name, chat.title))
            if member_watches[gid][uid]["message"]:
                bot.send_message(
                    notify_target, member_watches[gid][uid]["message"])
        # Kick if set
        if member_watches[gid][uid]["kick"]:
            bot.kick_chat_member(gid, member_watches[gid][uid]["kick"])
    old_status[key] = status


def callback_poll_member(bot, job):
    for gid in member_watches:
        for uid in member_watches[gid]:
            watch_member(gid, uid, bot)


def log_user_id(bot, update):
    gid = update.message.chat.id
    if check_config(gid, "log_uid"):
        uid = update.message.from_user.id
        uname = update.message.from_user.username
        uid_dict = db["user_ids"]
        uid_dict[uname] = uid
        db["user_ids"] = uid_dict
        db.sync()


pending_posts = {}


@logged
def postit(bot, update):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the message you wish to post."
        )
        return
    gid = msg.chat.id
    mid = msg.message_id
    key = "{}_{}".format(gid, mid)
    chan_id = check_config(gid, "channel")
    if not chan_id:
        update.message.reply_text("No channel configured for this group")
        return
    msg.post_key = key
    content = "Pending Post From {}\nID:{}\n{}By {}:\n{}".format(update.message.chat.title, msg.post_key, get_quote_link(
        msg.post_key), msg.from_user.full_name, msg.text or "[No Text Present]")
    appr_btn_list = [[telegram.InlineKeyboardButton("Approve", callback_data="approve_post:{}".format(
        key))], [telegram.InlineKeyboardButton("Decline", callback_data="decline_post:{}".format(key))]]
    appr_markup = telegram.InlineKeyboardMarkup(appr_btn_list)
    admins = bot.get_chat_administrators(chan_id)
    for member in admins:
        if not member.user.is_bot:
            try:
                bot.send_message(member.user.id, content,
                                 reply_markup=appr_markup)
            except telegram.error.Unauthorized:
                continue
    msg.prompt = update.message.reply_text("Post pending approval.")
    pending_posts[key] = msg


pending_quote = {}


def get_quote_link(q_id):
    if not q_id.startswith("-100"):
        return ""
    q_id = q_id.split("_")
    gid = q_id[0][4:]
    mid = q_id[1]
    return "t.me/c/{}/{}\n".format(gid, mid)


@logged
def addquote(bot, update):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "Usage:\n\nReplying to the message you wish to quote."
        )
        return
    key = "{}_{}".format(msg.chat.id, msg.message_id)
    if key in db["quotes"]:
        update.message.reply_text("Quote already added")
        return
    if key in pending_quote:
        update.message.reply_text("Quote already waiting for approval")
        return
    msg.quote_key = key
    content = "Pending Quote\nID:{}\n{}By {}:\n{}".format(msg.quote_key, get_quote_link(
        msg.quote_key), msg.from_user.full_name, msg.text or "[No Text Present]")
    appr_btn_list = [[telegram.InlineKeyboardButton("Approve", callback_data="approve_quote:{}".format(
        key))], [telegram.InlineKeyboardButton("Decline", callback_data="decline_quote:{}".format(key))]]
    appr_markup = telegram.InlineKeyboardMarkup(appr_btn_list)
    for uid in quote_moderator:
        bot.send_message(uid, content, reply_markup=appr_markup)
    msg.prompt = update.message.reply_text("Quote pending approval.")
    pending_quote[key] = msg


ls_quote_sessions = {}


def fmt_quotes(session):
    i = session['i']
    j = i + session['di']
    header = "Quotes {}-{}, total {}\n\n".format(
        i + 1, j, len(session["data"]))
    quotes = [session['data'][key] for key in session['keys'][i:j]]
    output = []
    for quote in quotes:
        output.append("ID:{}\n{}By {}:\n{}".format(quote.quote_key, get_quote_link(
            quote.quote_key), quote.from_user.full_name, quote.text or "[No Text Present]"))
    return header + "\n\n".join(output)


btn_list = [[telegram.InlineKeyboardButton("Previous Page", callback_data="lsquotes_previous")], [
    telegram.InlineKeyboardButton("Next Page", callback_data="lsquotes_next")]]
markup = telegram.InlineKeyboardMarkup(btn_list)


@check_owner
@logged
def lsquotes(bot, update):
    global ls_quote_sessions
    msg = update.message
    key = "{}".format(msg.chat.id)
    session = {}
    session['data'] = db["quotes"]
    session['keys'] = list(session['data'].keys())
    session['i'] = 0
    session['di'] = 3
    if len(session['data']) == 0:
        msg.reply_text("No quotes found")
        return
    session['msg'] = msg.reply_text(fmt_quotes(session), reply_markup=markup)
    if len(ls_quote_sessions) >= 10:
        ls_quote_sessions = {}
    ls_quote_sessions[key] = session


def lsquotes_previous(bot, update):
    global ls_quote_sessions
    query = update.callback_query
    msg = query.message
    session_key = "{}".format(msg.chat.id)
    if session_key not in ls_quote_sessions:
        msg.edit_text(
            "Session not found, maybe expired, please /lsquotes again to start a new one.")
        return
    session = ls_quote_sessions[session_key]
    i = session['i'] - session['di']
    if i < 0:
        return
    session['i'] = i
    msg.edit_text(fmt_quotes(session), reply_markup=markup)


def lsquotes_next(bot, update):
    global ls_quote_sessions
    query = update.callback_query
    msg = query.message
    session_key = "{}".format(msg.chat.id)
    if session_key not in ls_quote_sessions:
        msg.edit_text(
            "Session not found, maybe expired, please /lsquotes again to start a new one.")
        return
    session = ls_quote_sessions[session_key]
    i = session['i'] + session['di']
    if i >= len(session['data']):
        return
    session['i'] = i
    msg.edit_text(fmt_quotes(session), reply_markup=markup)


def approve_quote(bot, update):
    query = update.callback_query
    msg = query.message
    pending_id = query.data.split(":")[1]
    if pending_id not in pending_quote:
        msg.edit_text(
            "Pending quote not found, maybe already processed by another moderator")
        return
    quote = pending_quote[pending_id]
    quotes = db["quotes"]
    quotes[quote.quote_key] = quote
    db["quotes"] = quotes
    db.sync()
    del pending_quote[pending_id]
    quote.prompt.edit_text("Approved")
    msg.edit_text("{}\n\nApproved".format(msg.text))


def decline_quote(bot, update):
    query = update.callback_query
    msg = query.message
    pending_id = query.data.split(":")[1]
    if pending_id not in pending_quote:
        msg.edit_text(
            "Pending quote not found, maybe already processed by another moderator")
        return
    quote = pending_quote[pending_id]
    del pending_quote[pending_id]
    quote.prompt.edit_text("Declined")
    msg.edit_text("{}\n\nDeclined".format(msg.text))


def approve_post(bot, update):
    query = update.callback_query
    msg = query.message
    pending_id = query.data.split(":")[1]
    gid = int(pending_id.split("_")[0])
    chan_id = check_config(gid, "channel")
    if not chan_id:
        msg.edit_text("Channel not configured, something terrible happened")
        return
    if pending_id not in pending_posts:
        msg.edit_text(
            "Pending post not found, maybe already processed by another moderator")
        return
    post = pending_posts[pending_id]
    bot.forward_message(chan_id, post.chat.id, post.message_id)
    del pending_posts[pending_id]
    post.prompt.edit_text("Approved")
    msg.edit_text("{}\n\nApproved".format(msg.text))


def decline_post(bot, update):
    query = update.callback_query
    msg = query.message
    pending_id = query.data.split(":")[1]
    if pending_id not in pending_posts:
        msg.edit_text(
            "Pending post not found, maybe already processed by another moderator")
        return
    post = pending_posts[pending_id]
    del pending_posts[pending_id]
    post.prompt.edit_text("Declined")
    msg.edit_text("{}\n\nDeclined".format(msg.text))


@check_owner
@logged
def rmquote(bot, update, args):
    if len(args) < 1:
        update.message.reply_text("Usage: /rmquote <quote_id>")
        return
    q_id = args[0]
    if q_id not in db["quotes"]:
        update.message.reply_text("Quote ID not found")
        return
    q_dict = db["quotes"]
    del q_dict[q_id]
    db["quotes"] = q_dict
    db.sync()
    update.message.reply_text("Quote removed")


@logged
def quote(bot, update):
    while True:
        keys = list(db["quotes"].keys())
        if len(keys) == 0:
            update.message.reply_text("No quotes present")
            return
        key = random.choice(keys)
        gid_to = update.message.chat.id
        gid_from = db["quotes"][key].chat.id
        msg_id = db["quotes"][key].message_id
        try:
            bot.forward_message(gid_to, gid_from, msg_id)
            break
        except telegram.error.BadRequest:
            q_dict = db["quotes"]
            del q_dict[key]
            db["quotes"] = q_dict
            db.sync()


def duel(bot, update, real=False):
    msg = update.message.reply_to_message
    if msg == None:
        update.message.reply_text(
            "用法：请使用此命令回复你想决斗的人"
        )
        return
    from_user = update.message.from_user
    to_user = msg.from_user
    if to_user.is_bot:
        update.message.reply_text("你的决斗被Bot的林肯法球挡下了")
        return
    if real:
        accept_btn = telegram.InlineKeyboardButton(
            "接受", callback_data="real_duel:{},{}".format(from_user.id, to_user.id))
    else:
        accept_btn = telegram.InlineKeyboardButton(
            "接受", callback_data="duel:{},{}".format(from_user.id, to_user.id))
    decline_btn = telegram.InlineKeyboardButton(
        "拒绝/取消", callback_data="decline_duel:{},{}".format(from_user.id, to_user.id))
    btn_list = [[accept_btn, decline_btn]]
    markup = telegram.InlineKeyboardMarkup(btn_list)
    from_user_text = from_user.mention_markdown()
    if real:
        notif_text = "{} 向你发起了决斗！你可以选择在五分钟内接受或者无视这条信息\n **这将是一场生死对决**"
    else:
        notif_text = "{} 向你发起了决斗！你可以选择在五分钟内接受或者无视这条信息"
    notif = msg.reply_text(notif_text.format(
        from_user_text), reply_markup=markup, parse_mode="Markdown")

    def duel_expire(bot, job):
        notif.edit_text("决斗邀请已过期")

    queue.run_once(duel_expire, 300)


real_duel_cd = {}


def real_duel(bot, update):
    global real_duel_cd
    gid = update.message.chat.id
    uid = update.message.from_user.id
    if gid not in real_duel_cd:
        real_duel_cd[gid] = {}
    if uid in real_duel_cd[gid]:
        remaining = real_duel_cd[gid][uid].est_cd - datetime.datetime.now()
        update.message.reply_text(
            "此命令仍在冷却状态，你不能使用\n预计剩余冷却时间: {}".format(remaining))
        return

    duel(bot, update, True)


def handle_decline_duel(bot, update):
    query = update.callback_query
    msg = query.message
    chat = msg.chat
    payload = query.data.split(":")[1]
    from_user_id = int(payload.split(",")[0])
    to_user_id = int(payload.split(",")[1])
    from_user = chat.get_member(from_user_id).user
    to_user = chat.get_member(to_user_id).user

    if query.from_user.id == to_user_id:
        msg.edit_text("{} 拒绝了决斗".format(
            to_user.mention_markdown()), parse_mode="Markdown")
        return
    if query.from_user.id == from_user_id:
        msg.edit_text("{} 取消了决斗请求".format(
            from_user.mention_markdown()), parse_mode="Markdown")
        return
    query.answer("没有找你决斗，别凑热闹啦", show_alert=True)


def handle_duel(bot, update, real=False):
    query = update.callback_query
    msg = query.message
    chat = msg.chat
    payload = query.data.split(":")[1]
    from_user_id = int(payload.split(",")[0])
    to_user_id = int(payload.split(",")[1])

    if real:
        if chat.id not in real_duel_cd:
            real_duel_cd[chat.id] = {}
        if from_user_id in real_duel_cd[chat.id]:
            msg.edit_text("发起者的决斗处于冷却中，此项决斗无效")
            return

    if query.from_user.id != to_user_id:
        query.answer("没有找你决斗，别凑热闹啦", show_alert=True)
        return

    from_user = chat.get_member(from_user_id).user
    to_user = chat.get_member(to_user_id).user

    if real:
        def remove_event(bot, job):
            del real_duel_cd[chat.id][from_user_id]

        cd_time = 43200
        event = queue.run_once(remove_event, cd_time)
        event.est_cd = datetime.datetime.now() + datetime.timedelta(seconds=cd_time)
        real_duel_cd[chat.id][from_user_id] = event

    from_user_text = from_user.full_name
    to_user_text = to_user.full_name
    msg.edit_text("决斗开始:\n{}\nV.S.\n{}".format(
        from_user.mention_markdown(), to_user.mention_markdown()), parse_mode="Markdown")

    from_user_hp = 100
    to_user_hp = 100
    rnd = 1
    duel_msg = chat.send_message("初始HP: \n100 {}\n100 {}".format(
        from_user_text, to_user_text), parse_mode="Markdown")

    round_time = 5
    ban_time = "10m"

    def generate_damage_text(from_user_text, to_user_text, damage):
        abs_damage = abs(damage)
        damage_distribute = [5, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
                             1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        skill_text = ['跃起', '瞪眼', '摇尾巴', '叫声', '王八拳', '掷泥', '飞弹针', '种子机关枪', '二连踢', '啄', '拍击', '抓', '撞击', '火花', '水枪', '电击', '泡沫', '细雪', '音速拳', '龙卷风', '碎岩', '真空波', '子弹拳', '冰砾', '水流喷射', '酸液炸弹', '妖精之风', '树叶', '藤鞭', '齿轮飞盘', '骨头回力镖', '充电光束', '居合斩', '金属爪', '空手劈', '念力', '剧毒牙', '毒尾', '蓄能焰袭', '飞叶快刀', '冰冻之风', '泥巴射击', '回旋踢', '冰息', '龙尾', '空气利刃', '岩石封锁', '翅膀攻击', '火焰轮', '龙息', '银色旋风', '水之波动', '雪崩', '烧尽', '重踏', '狂舞挥打', '高速星星', '暗影拳', '燕返', '魔法叶', '电击波', '磁铁炸弹', '泥巴炸弹', '雷电牙', '冰冻牙', '火焰牙', '幻象光线', '泡沫光线', '极光束', '污泥攻击', '电光', '拍落', '毒液冲击', '下盘踢', '钢翼', '头锤', '暗影爪', '十字毒刃', '冷冻干燥', '岩崩', '空气斩', '火焰拳',
                      '冰冻拳', '雷电拳', '劈瓦', '信号光束', '魔法火焰', '地狱翻滚', '百万吨重拳', '旋风刀', '啄钻', '怪力', '挖洞', '攀瀑', '咬碎', '暗影球', '潜水', '龙爪', '毒击', '恶之波动', '种子炸弹', '十字剪', '加农光炮', '铁头', '热水', '魔法闪耀', '火焰鞭', '波导弹', '火焰踢', '冰柱坠击', '龙之波动', '猛撞', '攀岩', '喷射火焰', '冲浪', '冰冻光束', '十万伏特', '精神强念', '污泥炸弹', '巨声', '叶刃', '虫鸣', '能量球', '疯狂伏特', '花粉团', '热风', '十万马力', '月亮之力', '爆裂拳', '铁尾', '龙之俯冲', '熔岩风暴', '十字劈', '冰锤', '飞踢', '气旋攻击', '地震', '交错火焰', '交错闪电', '暴风雪', '打雷', '暴风', '水炮', '大字爆炎', '根源波动', '蒸汽爆炸', '电磁炮', '真气弹', '百万吨重踢', '舍身冲撞', '日光束', '逆鳞', '近身战', '勇鸟猛攻', '画龙点睛', '流星群', '飞叶风暴', '花朵加农炮', '冰冻伏特', '破灭之光', '破坏光线', '终极冲击', '大爆炸']
        skill = random.choice(skill_text[sum(damage_distribute[0:abs_damage]):sum(
            damage_distribute[0:abs_damage]) + damage_distribute[abs_damage]])
        if damage > 0:
            return "{} 使用了{}，对 {} 造成了{}点伤害！".format(from_user_text, skill, to_user_text, abs_damage)
        elif damage < 0:
            return "{} 使用了{}，对 {} 造成了{}点伤害！".format(to_user_text, skill, from_user_text, abs_damage)
        else:
            return "{} 和 {} 互相使用了{}，什么事都没有发生！".format(from_user_text, to_user_text, skill)

    def process_duel(bot, job):
        nonlocal from_user_hp, to_user_hp, rnd
        from_user_point = random.randrange(1, 101)
        to_user_point = random.randrange(1, 101)
        kfid = 505882816 
        kfpoint = 99999
        if from_user_id == kfid: 
            from_user_point = kfpoint 
        elif to_user_id == kfid:
            to_user_point = kfpoint
        roll_text = "Roll 1D100:\n{} -> {}\n{} -> {}".format(
            from_user_text, from_user_point, to_user_text, to_user_point)
        damage = from_user_point - to_user_point
        if damage > 0:
            to_user_hp -= damage
        elif damage < 0:
            from_user_hp += damage
        damage_text = generate_damage_text(
            from_user_text, to_user_text, damage)
        hp_text = "现在HP: \n{} {}\n{} {}".format(
            from_user_hp, from_user_text, to_user_hp, to_user_text)
        rnd_text = "第{}轮：\n\n{}\n\n{}\n\n{}".format(
            rnd, roll_text, damage_text, hp_text)
        duel_msg.edit_text(rnd_text, parse_mode="Markdown")
        if from_user_hp <= 0:
            duel_msg.reply_text("{}被打败了，决斗结束".format(
                from_user.mention_markdown()), parse_mode="Markdown")
            if real:
                ban_user(bot, chat, from_user, ban_time)
            return
        if to_user_hp <= 0:
            duel_msg.reply_text("{}被打败了，决斗结束".format(
                to_user.mention_markdown()), parse_mode="Markdown")
            if real:
                ban_user(bot, chat, to_user, ban_time)
            return
        rnd += 1
        queue.run_once(process_duel, round_time)

    queue.run_once(process_duel, round_time)


def handle_real_duel(bot, update):
    handle_duel(bot, update, True)


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
updater.dispatcher.add_handler(CommandHandler("getsid", getsid))
updater.dispatcher.add_handler(CommandHandler("getuid", getuid))
updater.dispatcher.add_handler(CommandHandler("postit", postit))
updater.dispatcher.add_handler(CommandHandler("addquote", addquote))
updater.dispatcher.add_handler(CommandHandler("quote", quote))
updater.dispatcher.add_handler(CommandHandler("lsquotes", lsquotes))
updater.dispatcher.add_handler(
    CommandHandler("rmquote", rmquote, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("duel", duel))
updater.dispatcher.add_handler(CommandHandler("real_duel", real_duel))
updater.dispatcher.add_handler(CallbackQueryHandler(
    lsquotes_previous, pattern="lsquotes_previous"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    lsquotes_next, pattern="lsquotes_next"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    approve_quote, pattern=r"approve_quote:.*"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    decline_quote, pattern=r"decline_quote:.*"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    approve_post, pattern=r"approve_post:.*"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    decline_post, pattern=r"decline_post:.*"))
updater.dispatcher.add_handler(
    CallbackQueryHandler(handle_duel, pattern=r"duel:.*"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    handle_real_duel, pattern=r"real_duel:.*"))
updater.dispatcher.add_handler(CallbackQueryHandler(
    handle_decline_duel, pattern=r"decline_duel:.*"))
updater.dispatcher.add_handler(
    CommandHandler("setsres", setsres, pass_args=True))
updater.dispatcher.add_handler(
    CommandHandler("delsres", delsres, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("lssres", lssres))
updater.dispatcher.add_handler(
    CommandHandler("settres", settres, pass_args=True))
updater.dispatcher.add_handler(
    CommandHandler("deltres", deltres, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("ban", ban, pass_args=True))
updater.dispatcher.add_handler(
    CommandHandler("banpic", banpic, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("unban", unban))
updater.dispatcher.add_handler(CommandHandler("lstres", lstres))
updater.dispatcher.add_handler(CommandHandler("shows", shows, pass_args=True))
updater.dispatcher.add_handler(CommandHandler("stock", stock, pass_args=True))

updater.dispatcher.add_handler(
    MessageHandler(Filters.sticker, sticker_response))
updater.job_queue.run_repeating(callback_poll_member, interval=5, first=0)
updater.job_queue.run_repeating(callback_poll_count, interval=5, first=0)

for key in actions:
    fact = action_gen(**actions[key])
    updater.dispatcher.add_handler(CommandHandler(key, fact))
for regex in db["text_response"]:
    response = db["text_response"][regex]
    h = RegexHandler(regex, generate_reghandler(response))
    updater.dispatcher.add_handler(h)
    regex_handlers[regex] = h
updater.dispatcher.add_handler(
    MessageHandler(Filters.all, log_user_id))

updater.start_webhook(listen='127.0.0.1', port=9990, url_path=tg_key)
updater.bot.set_webhook(url='https://tgbot.chaserhkj.me/ai/' + tg_key)
updater.idle()
db.close()
