# LDSGeneralConferenceDownloader
A script to download General Conference talks for offline listening.

## Who is this for?
This script is ideal for:
 - Going on *long journeys* without reliable internet connection,
 - *Full-time missionaries* who want to listen to conference talks during study time,
 - *Anyone* who wishes to study from the conference talks but doesn't have a reliable internet connection.
  
## What it can do?
This script will allow you to download the LDS General Conference talks in mp3 form that are available at https://www.churchofjesuschrist.org/study/general-conference.
It will create *playlists* as *.m3u files to allow you to play an *entire session*. 
It will also create playlists for *speakers* and *topics*.
This will not only work with the default English versions, but also for *every other language* for which audio files are available.
Currently, hundreds of talks are available in many languages, going back as far as 1971 for some.

## How does it work?
It will programmatically navigate the churchofjesuschrist.org website, downloading and organising every talk of interest to you.
Everything will be saved to a local folder of your choice. 
Load these files onto a *memory stick* for your car, or into your *favourite media player*. 

## What do I need to do to run this script?
1. Install Python 3. If you don't have Python installed on your system, then follow the instructions here to install it: https://www.python.org/downloads/
2. The script needs some external library functionality. Using the terminal, navigate to this folder, then run the command:
`pip install -r requirements.txt`
3. The script is run as follows:
`python gen_conf_downloader.py`
4. There are a number of optional arguments that my be added to the above command (run `python gen_conf_downloader.py -h`
 for full list):

|Argument|Values|Meaning|
|--------|------|-------|
|`-h` or `--help`| |List all arguments and exit|
|`-l` or `-lang`| 3-letter language code|Indicates which language version is to be downloaded. See https://www.churchofjesuschrist.org/languages for full list. Click on the language you want, then take note of the 3-letter code in the address bar. i.e. https://www.churchofjesuschrist.org/?lang=*spa*|
|`-s` or `-start`|Year as 4 digit number|First year of conference to download. Defaults to 1971. _Note: not all historic sessions are available in all languages_|
|`-e` or `-end`|Year as 4 digit number|Last year to download (defaults to current year).|
|`-d` or `-dest`|folder relative to here. i.e. `./conference`|Destination folder to output files to. Defaults to `output`|
|`-n` or `-nocleanup`| |Leaves temporary files after process completion.|
|`-v` or `-verbose`| |Provides detailed activity logging instead of progress bars.|
|`-nonumbers`| |Skips adding numbers to session directory names.|
|`-noplaylists`| |Skips creating m3u playlist files.|
|`-notopics`| |Skip downloading speakers by topic.|
|`-speaker-min`| |Minimum number of talks to create a speaker playlist file.|
|`-nogui`| |Use command line only to show progress.|

 _Note: Depending upon how many years worth of conferences you ask it to download, it may take some time!_

## How do I create an executable to share with family and friends?
1. Follow steps 1 and 2 under "What do I need to do to run this script?"
2. Install pyinstaller
`pip install pyinstaller`
3. Create executable using pyinstaller (WINDOWS)
`pyinstaller -F -n GeneralConferenceDownloader --add-data="conference_headers.json;." gen_conf_downloader.py`
4. Share dist/GeneralConferenceDownloader.exe with your family and friends

## What does it generate?
It will generate a folder structure as follows in your destination folder:
```
output
└───General Conference (eng)
    └───Conferences
    │   2021-(87, 7h44m).m3u
    │   2021-April-(87, 7h44m).m3u
    │   2021-April-Saturday Morning Session-(87, 7h44m).m3u
    │   2021-April-Saturday Afternoon Session-(87, 7h44m).m3u
    │   ...
    └───MP3
    │   └───2021
    │   │   └───April
    │   │   │   └───10-Saturday Morning Session
    │   │   │   │   ...
    │   │   │   └───20-Saturday Afternoon Session
    │   │   │   │   ...
    │   │   │   └───30-Priesthood Session
    │   │   │   │   31 Am I a Child of God? (Brian K. Taylor).mp3
    │   │   │   │   32 Even as Christ Forgives You, So Also Do Ye (Larry J. Echo Hawk).mp3
    │   │   │   │   ...
    │   │   └───October
    │   └───2017
    │       ...
    └───Speakers
    │   D. Todd Christofferson-(2021-2010, 1, 13m).m3u
    │   Dallin H. Oaks(2021-2000, 3, 45m).m3u
    │   ...
    └───Topics
        Adversity-(3, 44m).m3u
        Atonement-(6, 1h4m).m3u
        ...
```        
The playlists for the Topics and Speakers include in parenthesis the number of talks and the total duration and talk min/max year range for speakers.
