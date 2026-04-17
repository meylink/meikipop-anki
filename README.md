# AI SLOP OF AI SLOP FORK OF MEIKIPOP WITH ANKI/YOMITAN

This is an ai slop of an ai slop vibecoded fork of meikipop with anki integration and other yomitan-like features for Wayland.



https://github.com/user-attachments/assets/b0720ecc-4904-499f-8baa-f8352e35a824




## New Features

- Anki card creation, it works like yomitan (mostly)
- Shows frequency and pitch accent
- Uses yomitan-api to automatically get your dictionaries, works with bilingual and monolingual (the ones I tried at least)
- Most features are toggleable, you can have a normal meikipop popup with just anki card creation
- Only tested on KDE Wayland.


## Installation

1. Install Python 3.10+.
2. Clone this fork: `git clone https://github.com/zurcGH/meikipop-anki.git`.
3. Install dependencies: `meikipop.install.bat` or `pip install -r requirements.txt`.
4. Install Yomitan API: `install_yomitan_api.bat` or `python scripts/setup_yomitan_api.py`. If you use Firefox or built Yomitan from source, you need to find your extension ID, you can find how to get it [here](https://github.com/yomidevs/yomitan-api).
5. Run: `meikipop.run.bat` or `python -m src.main`.
6. Optional: `meikipop.build.bat` to build an exe file, after that you can delete everything except the yomitan-api folder (stored in src).

Notes : 
- On auto-mode, hold Shift to keep overlay open and cycle through entries.
- Keybinds only work with Alt, Shift, Ctrl and Mouse buttons (need to be added through config.ini).
- There's a "Raw Yomitan Overlay" mode, where the styling looks a bit better. Selecting "glossary-raw" for Main Definition sends the same styling to Anki.

## Acknowledgements

- This is a fork of rtr46's [meikipop](https://github.com/rtr46/meikipop)
- Used code from pnotisdev's [fork](https://github.com/pnotisdev/meikipop) and Kellenok's [fork](https://github.com/Kellenok/meikipop/tree/feature/yomitan-integration)
- Used code from zurcGH's [fork](https://github.com/zurcGH/meikipop-anki) and from KamWithK's [fork](https://github.com/KamWithK/meikipop) for Wayland support.

## License

Meikipop is licensed under the GNU General Public License v3.0. See `LICENSE` for the full text.

Original credit: https://github.com/rtr46/meikipop
