# main.py
import asyncio, sys, os
sys.path.append(os.path.dirname(__file__))

from ellie import Game   # adjust if your Game class lives elsewhere

async def main():
    g = Game()
    while True:
        if g.state == "TITLE":   g.handle_title()
        elif g.state == "PLAYING": g.handle_play()
        elif g.state == "PAUSED":  g.handle_pause()
        elif g.state == "NAME":    g.handle_name()
        elif g.state == "LEADER":  g.handle_leader()
        elif g.state == "SKINS":   g.handle_skins()
        else:
            break
        await asyncio.sleep(0)   # required for browser
if __name__ == "__main__":
    asyncio.run(main())
