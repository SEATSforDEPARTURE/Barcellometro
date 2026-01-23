from app.core.bot import create_bot

def main():
    bot = create_bot()
    bot.run(bot.settings.DISCORD_TOKEN)

if __name__ == "__main__":
    main()
