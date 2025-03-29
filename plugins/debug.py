import asyncio
import contextlib
import html
import io
import sys

import aiohttp
import pyrogram
from meval import meval
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core import config, delta
from utils import format_sec

TASKS = {}
BUTTON_ABORT = [[InlineKeyboardButton("Abort", callback_data="btn_abort")]]
BUTTON_RERUN = [[InlineKeyboardButton("Refresh", callback_data="btn_rerun")]]


def sudo_users(_, __, event: Message | CallbackQuery) -> bool:
    return event.from_user.id in config.owner_id if event.from_user else False


fltSudo = filters.create(sudo_users, "fltSudo")


@Client.on_callback_query(fltSudo & filters.regex(r"^btn_"))
async def evaluate_handler_(client: Client, callback_query: CallbackQuery) -> None:
    command = callback_query.data.split("_")[1]
    chat_id = callback_query.message.chat.id
    message = await client.get_messages(
        chat_id, callback_query.message.reply_to_message.id
    )
    reply_message = callback_query.message

    if command == "rerun":
        _id_ = f"{chat_id} - {message.id}"
        task = asyncio.create_task(async_evaluate_func(client, message, reply_message))
        TASKS[_id_] = task
        try:
            await task
        except asyncio.CancelledError:
            await reply_message.edit_text(
                "<b>Process Cancelled!</b>",
                reply_markup=InlineKeyboardMarkup(BUTTON_RERUN),
            )
        finally:
            TASKS.pop(_id_, None)
    elif command == "abort":
        cancel_task(task_id=f"{chat_id} - {message.id}")


@Client.on_message(fltSudo & filters.command(["e", "eval"]))
async def evaluate_handler(client: Client, message: Message) -> None:
    if len(message.command) == 1:
        await message.reply_text(
            "<b>No Code!</b>",
            quote=True,
            reply_markup=InlineKeyboardMarkup(BUTTON_RERUN),
        )
        return

    reply_message = await message.reply_text(
        "...", quote=True, reply_markup=InlineKeyboardMarkup(BUTTON_ABORT)
    )

    _id_ = f"{message.chat.id} - {message.id}"
    task = asyncio.create_task(async_evaluate_func(client, message, reply_message))
    TASKS[_id_] = task
    try:
        await task
    except asyncio.CancelledError:
        await reply_message.edit_text(
            "<b>Process Cancelled!</b>", reply_markup=InlineKeyboardMarkup(BUTTON_RERUN)
        )
    finally:
        TASKS.pop(_id_, None)


@Client.on_message(fltSudo & filters.command("sh"))
async def shell_handler(client: Client, message: Message) -> None:
    if len(message.command) == 1:
        await message.reply_text("<b>No Code!</b>", quote=True)
        return

    reply_message = await message.reply_text("...")
    shell_code = message.text.split(maxsplit=1)[1]

    init_time = client.loop.time()
    sub_process_sh = await asyncio.create_subprocess_shell(
        shell_code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await sub_process_sh.communicate()
    bash_print_out = (stdout + stderr).decode().strip()

    converted_time = format_sec(client.loop.time() - init_time)
    final_output = f"<pre>{bash_print_out}</pre>\n<b>Elapsed:</b> {converted_time}"

    if len(final_output) > 4096:
        paste_url = await paste_rs(str(bash_print_out))
        bash_buttons = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Output", url=paste_url)]]
        )
        await reply_message.edit_text(
            f"<b>Elapsed:</b> {converted_time}",
            reply_markup=bash_buttons,
            disable_web_page_preview=True,
        )
    else:
        await reply_message.edit_text(final_output)


async def async_evaluate_func(
    client: Client, message: Message, reply_message: Message
) -> None:
    await reply_message.edit_text(
        "<b>Executing...</b>", reply_markup=InlineKeyboardMarkup(BUTTON_ABORT)
    )

    if len(message.text.split()) == 1:
        await reply_message.edit_text(
            "<b>No Code!</b>", reply_markup=InlineKeyboardMarkup(BUTTON_RERUN)
        )
        return

    eval_vars = {
        "asyncio": asyncio,
        "os": __import__("os"),
        "sys": sys,
        "src": __import__("inspect").getsource,
        "pyrogram": pyrogram,
        "enums": pyrogram.enums,
        "errors": pyrogram.errors,
        "raw": pyrogram.raw,
        "types": pyrogram.types,
        "client": client,
        "delta": delta,
        "bot": delta.bot_client,
        "user": delta.user_client,
        "msg": message,
        "chat": message.chat,
        "replied": message.reply_to_message,
        "datetime": __import__("datetime"),
        "re": __import__("re"),
        "json": __import__("json"),
        "random": __import__("random"),
        "logging": __import__("logging"),
        "traceback": __import__("traceback"),
        "itertools": __import__("itertools"),
        "collections": __import__("collections"),
        "pathlib": __import__("pathlib"),
    }

    eval_code = message.text.split(maxsplit=1)[1]
    start_time = client.loop.time()

    file = io.StringIO()
    langcode = "python"
    with contextlib.redirect_stdout(file):
        try:
            meval_out = await meval(eval_code, globals(), **eval_vars)
            print_out = file.getvalue().strip() or str(meval_out) or "None"
        except Exception as exception:
            langcode = type(exception).__name__
            print_out = str(exception)

    converted_time = format_sec(client.loop.time() - start_time)
    final_output = f"<pre language={langcode}>{html.escape(print_out)}</pre>\n<pre language=Elapsed>{converted_time}</pre>"

    eval_buttons = BUTTON_RERUN.copy()
    if len(final_output) > 4096:
        paste_url = await paste_rs(str(print_out))
        eval_buttons.insert(0, [InlineKeyboardButton("Output", url=paste_url)])
        await reply_message.edit_text(
            f"<b>Elapsed:</b> {converted_time}",
            reply_markup=InlineKeyboardMarkup(eval_buttons),
        )
    else:
        await reply_message.edit_text(
            final_output, reply_markup=InlineKeyboardMarkup(eval_buttons)
        )


async def paste_rs(content: str) -> str:
    async with aiohttp.ClientSession() as client:
        async with client.post("https://paste.rs", data=content) as resp:
            resp.raise_for_status()
            return (await resp.text()).strip()


def cancel_task(task_id: str) -> None:
    task = TASKS.get(task_id)
    if task and not task.done():
        task.cancel()
