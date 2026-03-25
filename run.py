"""
START THE BOT
=============
Just run:   python run.py

That's it. The bot will:
  • Wait until market hours if it's outside 9:30am–4pm ET
  • Scan your tickers every 15 minutes during market hours
  • Run a self-improvement analysis each morning at 8am–9:25am ET
"""

from bot import main

if __name__ == "__main__":
    main()
