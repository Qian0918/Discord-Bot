import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} 已上線！')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.content.startswith('hello'):
        await message.channel.send('Hello, World!')
    await bot.process_commands(message)

bot.run('MTQ3ODM0OTc3OTM5NzI0NzA4Nw.Gg8vpX.syRcN75cpOXTCQksAAIglsJaCNmJxtRKTfHRU4')
