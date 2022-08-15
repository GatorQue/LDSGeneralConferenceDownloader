"""
Script to download LDS General Conference MP3s, creating playlists for each conference, speaker and topic
"""

import argparse
import base64
import datetime
import glob
import io
import json
import os
import pathlib
import re
import shutil
import sys

import colorama
from collections import namedtuple
import html as html_tools
from html.parser import HTMLParser
CLI_ONLY = False
try:
    import PySimpleGUI as sg
except ImportError:
    CLI_ONLY = True
from tqdm import tqdm
from urllib.parse import unquote_plus
from urllib.parse import quote_plus
import urllib.request
import zlib
from mutagen.mp3 import MP3

Conference = namedtuple('Conference', 'link title year month')
Session = namedtuple('Session', 'conference link title number')
Talk = namedtuple('Talk', 'session link title speaker topics')
Audio = namedtuple('Audio', 'link file')
Topic = namedtuple('Topic', 'link topic')
TalkByTopic = namedtuple('TalkByTopic', 'link speaker title topic')

LDS_ORG_URL = 'https://www.churchofjesuschrist.org'
ALL_CONFERENCES_URL = f'{LDS_ORG_URL}/study/general-conference'
ALL_TOPICS_URL = f'{LDS_ORG_URL}/study/general-conference/topics'

GET_LANGS_REGEX = 'data-lang=\".*?\" data-clang=\"(.*?)\">(.*?)</a>'
CONFERENCES_REGEX = '<a[^>]*href="([^"]*)"[^>]*><div[^>]*><img[^>]*></div><span[^>]*>([A-Z][a-z]* \d{4})</span></a>'
CONFERENCE_GROUPS_REGEX = '<a[^>]*href="([^"]*)"[^>]*><div[^>]*><img[^>]*></div><span[^>]*>(\d{4}.\d{4})</span></a>'
CONFERENCE_GROUPS_RANGE_REGEX = '.*/(\d{4})(\d{4})\?lang=.*'
CONFERENCE_LINK_YEAR_MONTH_REGEX = '.*(\d{4})/(\d{2})\?lang=.*'

SCRIPT_BASE64_REGEX = '<script>window.__INITIAL_STATE__[^"]*"([^"]*)";</script>'
MP3_DOWNLOAD_REGEX = '<a[^>]*href="([^"]*)"[^>]*>This Page \(MP3\).*?</a>'
MP3_DOWNLOAD_FILENAME_REGEX = '.*/(.*\.mp3)\?lang=.*'
MP3_MEDIAURL_REGEX = '{"mediaUrl":"([^"]*)","variant":"audio"}'
MP3_MEDIAURL_FILENAME_REGEX = '.*/(.*\.mp3)'

SESSIONS_REGEX = '<a[^>]*href="([^"]*)"[^>]*><div[^>]*><p><span[^>]*>([^<]*)</span></p></div></a><ul[^>]*>(.*?)</ul>'
SESSION_TALKS_REGEX = '<a[^>]*href="([^"]*)"[^>]*><div[^>]*><p><span[^>]*>([^<]*)</span></p><p[^>]*>([^<]*)</p></div></a>'

TOPICS_REGEX = '<a[^>]*href=([^"]*)><div[^>]*><div[^>]*><div[^>]*><h4[^>]*>([^<]*)</h4></div></div></div><hr[^>]*></a>'
TOPIC_TALKS_REGEX = '<a[^>]*href=([^"]*)><div[^>]*><div[^>]*><div[^>]*><h6[^>]*>[^<]*</h6><h6[^>]*>([^<]*)</h6></div><div[^>]*><h4[^>]*>([^<]*)</h4></div></div>.*?</a>'


class DummyTqdm:
    def __init__(self, total=None, unit="it"):
        self.total = total
        print("Creating conference downloader Dummy progress bar")

    def __len__(self):
        return self.total

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_description_str(self, desc=None, refresh=True):
        pass

    def update(self, n=1):
        pass

    def write(self, string, file=sys.stdout, end="\n"):
        sys.stderr.write(string + end)


class GuiTqdm:
    def __init__(self, total=None, unit="it"):
        self.total = total
        self.last = 1
        self.running = True

    def __len__(self):
        return self.total

    def __enter__(self):
        layout = [[sg.Text('', font=('Helvetica', 16), key='-TITLE-', size=(60, 1))],
                  [sg.Text("", key='-DESC-', size=(60, 1))],
                  [sg.ProgressBar(self.total, orientation='h', size=(60, 20), key='-PROG-')],
                  [sg.Cancel(focus=True, size=(10,3))]]
        self.window = sg.Window('General Conference Downloader', layout, finalize=True)
        return self

    def __exit__(self, *exc):
        self.window.close()
        self.window = None
        if not self.running:
            sys.exit(2)
        return False

    def set_description_str(self, desc=None, refresh=True):
        self.window['-DESC-'].update(desc)
        self._check_events()

    def update(self, n=1):
        self.last += n
        self.window['-PROG-'].update(self.last)
        self._check_events()

    def write(self, string, file=sys.stdout, end="\n"):
        self.window['-TITLE-'].update(string)

    def _check_events(self):
        event, values = self.window.read(timeout=0)
        if event == 'Cancel' or event == sg.WIN_CLOSED:
            self.running = False


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = io.StringIO()
    def handle_data(self, d):
        self.text.write(d)
    def get_data(self):
        return self.text.getvalue()


def add_headers(request):
    with open(get_resource_path('conference_headers.json'), 'r') as f:
        headers = json.load(f)

    for key in headers:
        request.add_header(key, headers[key])


def add_to_cache(args, html, url):
    url = html_tools.unescape(url).encode()
    url = quote_plus(url)
    path = get_cache_filename(args, url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding="utf-8") as f:
        f.write(html)


def clean_title(title):
    s = MLStripper()
    s.feed(title)
    keepcharacters = (' ', '-', '_', '.')
    return "".join(c for c in s.get_data() if c.isalnum() or c in keepcharacters).rstrip()


def create_playlists(args, all_talks):
    playlists = dict()
    for talk in all_talks:
        year_path = get_year_path(args, talk.session.conference)
        month_path = get_month_path(args, talk.session.conference)
        session_path = get_session_path(args, talk.session, nonumbers=True)
        playlists.setdefault(f'Conferences/{year_path}', [])
        playlists.setdefault(f'Conferences/{year_path}-{month_path}', [])
        playlists.setdefault(f'Conferences/{year_path}-{month_path}-{session_path}', [])
        playlists.setdefault(f'Speakers/{talk.speaker}', [])
        for topic in talk.topics:
            playlists.setdefault(f'Topics/{topic}', [])
    return playlists


def decode(text):
    return unquote_plus(text)


def download_all_content(args):
    # Retrieve links to all sessions and talks
    all_talks = get_all_talks(args)

    # Create playlists from all talks gathered above
    if not args.noplaylists:
        playlists = create_playlists(args, all_talks)

    # Now download talk HTML, audio, and build playlist links
    with tqdm(total=len(all_talks), unit="talks") as progress_bar:
        if args.noplaylists:
            progress_bar.write("Retrieving talk audio files")
        else:
            progress_bar.write("Retrieving talk audio files and updating playlists")
        for talk in all_talks:
            progress_bar.set_description_str(talk.title, refresh=True)
            audio = get_audio(args, talk)
            if audio and download_audio(progress_bar, args, get_relative_path(args, talk.session), audio):
                if not args.noplaylists:
                    update_playlists(args, playlists, talk, audio)
            progress_bar.update(1)
            if hasattr(progress_bar, 'running') and not progress_bar.running:
                break

    # Now write out playlists
    if not args.noplaylists:
        write_playlists(args, playlists)

    # Optionally remove cached HTML files
    if not args.nocleanup:
        remove_cached_files(args)


def download_audio(progress_bar, args, relpath, audio):
    # If audio file doesn't yet exist, attempt to retrieve it
    file_path = f'{get_output_dir(args)}/{relpath}/{audio.file}'
    if not os.path.isfile(file_path):
        try:
            req = urllib.request.Request(audio.link)
            with urllib.request.urlopen(req) as response:
                data = response.read()
                write_mp3_to_disk(data, file_path)
                return data
        except Exception as err:
            # Remove partial audio file download
            if os.path.isfile(file_path):
                os.remove(file_path)
            progress_bar.write(err, file=sys.stderr)
            return False
    return True


def get_all_conferences(args):
    # Retrieve list of all available conferences
    all_conferences_html = get_html(args, f'{ALL_CONFERENCES_URL}?lang={args.lang}', nocache=args.nocleanup)
    all_conferences = get_conferences(args, all_conferences_html)
    all_conferences.extend(get_range_conferences(args, all_conferences_html))
    # List is newest to oldest, reverse it before returning list
    all_conferences.reverse()
    return all_conferences


def get_all_languages_map(args):
    all_languages_html = get_html(args, f'{LDS_ORG_URL}/languages', nocache=args.nocleanup)
    all_languages_list = re.findall(GET_LANGS_REGEX, all_languages_html, re.S)
    return dict(all_languages_list)


def get_all_talks(args):
    # First retrieve all conferences that match start/end years in args
    all_conferences = get_all_conferences(args)

    # Next retrieve all talks by topic if playlists are enabled
    if args.noplaylists:
        all_talks_by_topic = []
    else:
        all_talks_by_topic = get_all_talks_by_topic(args)

    all_talks = []
    with tqdm(total=len(all_conferences), unit="conferences") as progress_bar:
        progress_bar.write("Retrieving all general conference sessions and talk links and titles")
        for conference in all_conferences:
            conference_html = get_html(args, f'{LDS_ORG_URL}{decode(conference.link)}', nocache=args.nocleanup)
            sessions = re.findall(SESSIONS_REGEX, conference_html, re.S)
            for num, session_info in enumerate(sessions, start=1):
                progress_bar.set_description_str(f'{conference.title}-{session_info[1]}', refresh=True)
                session = Session(conference, session_info[0], session_info[1], num*10)
                talks = re.findall(SESSION_TALKS_REGEX, session_info[2], re.S)
                for talk_info in talks:
                    title = clean_title(talk_info[1])
                    speaker = talk_info[2]
                    topics = [tbt.topic for tbt in all_talks_by_topic if tbt.title == title and tbt.speaker == speaker]
                    all_talks.append(Talk(session, talk_info[0], title, speaker, topics))
                    if hasattr(progress_bar, 'running') and not progress_bar.running:
                        break
                if hasattr(progress_bar, 'running') and not progress_bar.running:
                    break
            progress_bar.update(1)
            if hasattr(progress_bar, 'running') and not progress_bar.running:
                break
    return all_talks


def get_all_topics(args):
    all_topics_html = get_html(args, f'{ALL_TOPICS_URL}?lang={args.lang}', nocache=args.nocleanup)
    return [Topic(topic[0], topic[1]) for topic in re.findall(TOPICS_REGEX, all_topics_html, re.S)]


def get_all_talks_by_topic(args):
    all_topics = get_all_topics(args)
    topic_talks = []
    with tqdm(total=len(all_topics), unit="topics") as progress_bar:
        progress_bar.write("Retrieving all topics")
        for topic in all_topics:
            progress_bar.set_description_str(topic.topic)
            topic_html = get_html(args, f'{LDS_ORG_URL}{decode(topic.link)}', nocache=args.nocleanup)
            topic_talks.extend([TalkByTopic(tt[0], tt[1], clean_title(tt[2]), topic.topic) for tt in re.findall(TOPIC_TALKS_REGEX, topic_html, re.S)])
            progress_bar.update(1)
            if hasattr(progress_bar, 'running') and not progress_bar.running:
                break
    return topic_talks


def get_audio(args, talk):
    link_html = get_html(args, f'{LDS_ORG_URL}{decode(talk.link)}')
    mp3_link = re.search(MP3_DOWNLOAD_REGEX, link_html)
    # In April 2022 the MP3 link became buried in base64 encoded script section
    match = re.search(SCRIPT_BASE64_REGEX, link_html)
    if mp3_link:
        # Extract and reuse the filename from the MP3 URL (exclude language)
        mp3_file = re.match(MP3_DOWNLOAD_FILENAME_REGEX, mp3_link.group(1))
    elif not mp3_link and not match:
        return
    elif not mp3_link and match:
        # MP3 link is probably in the base64 encoded script section
        script_data = str(base64.b64decode(match.group(1)))
        # Search for JSON object containing mediaUrl key and value
        mp3_link = re.search(MP3_MEDIAURL_REGEX, script_data)
        if not mp3_link:
            return
        # Extract and reuse the filename from the MP3 URL
        mp3_file = re.match(MP3_MEDIAURL_FILENAME_REGEX, mp3_link.group(1))

    if not mp3_file:
        return

    # Create audio object with link and filename
    return Audio(mp3_link.group(1), mp3_file.group(1))


def get_cache_filename(args, url):
    return f'{args.cache_home}/{args.lang}/{url}'


def get_conferences(args, conferences_html):
    conferences = re.findall(CONFERENCES_REGEX, conferences_html, re.S)
    result = []
    for conference in conferences:
        match = re.match(CONFERENCE_LINK_YEAR_MONTH_REGEX, conference[0])
        if not match:
            continue
        year = int(match.group(1))
        if year < args.start or year > args.end:
            continue
        month = int(match.group(2))
        result.append(Conference(conference[0], conference[1], year, month))
    return result


def get_duration_text(duration_secs):
    mins = int((duration_secs / 60) % 60)
    hours = int((duration_secs / (60 * 60)) % 24)
    days = int((duration_secs / (60 * 60 * 24)) % 7)
    weeks = int((duration_secs / (60 * 60 * 24 * 7)))
    text = ''
    if weeks:
        text += f'{weeks}w'
    if days:
        text += f'{days}d'
    if hours:
        text += f'{hours}h'
    if mins:
        text += f'{mins}m'
    return text


def get_from_cache(args, url):
    url = html_tools.unescape(url)
    url = quote_plus(url)

    path = get_cache_filename(args, url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        with open(path, 'r', encoding="utf-8") as f:
            return f.read()
    return None


def get_html(args, url, nocache=False):
    url = html_tools.unescape(url)
    req = urllib.request.Request(url)
    add_headers(req)

    if not nocache:
        cached = get_from_cache(args, url)
        if cached:
            if args.verbose:
                print("Reading cached: {}".format(url))
            return cached

    if args.verbose:
        print("Retrieving: {}".format(url))

    try:
        with urllib.request.urlopen(req) as response:
            data = response.read()
            decompressed_data = zlib.decompress(data, 16 + zlib.MAX_WBITS)
            html = decompressed_data.decode("utf-8")
            if not nocache:
                add_to_cache(args, html, url)
            return html
    except Exception as ex:
        sys.stderr.write(f'Problem with http request ({url}: {ex}')
        return ''


def get_month_path(args, conference):
    if 4 == conference.month:
        return 'April'
    else:
        return 'October'


def get_output_dir(args):
    return f'{args.dest}/GeneralConference ({args.lang})'


def get_playlist_info(first, last, count, duration_secs):
    mins = int((duration_secs / 60) % 60)
    hours = int((duration_secs / (60 * 60)) % 24)
    days = int((duration_secs / (60 * 60 * 24)) % 7)
    weeks = int((duration_secs / (60 * 60 * 24 * 7)))
    if first and last:
        text = f'{first}-{last}, '
    else:
        text = ''
    if count:
        text += f'{count}, '
    text += get_duration_text(duration_secs)
    return text


def get_range_conferences(args, conferences_html):
    conference_groups = re.findall(CONFERENCE_GROUPS_REGEX, conferences_html, re.S)
    result = []
    # Retrieve list of older conferences from conference groups
    for conference_group in conference_groups:
        match = re.match(CONFERENCE_GROUPS_RANGE_REGEX, conference_group[0])
        if not match:
            continue
        end_year = int(match.group(2))
        start_year = int(match.group(1))
        if end_year < args.start or start_year > args.end:
            continue
        conference_group_html = get_html(args, f'{LDS_ORG_URL}{decode(conference_group[0])}')
        if conference_group_html:
            result.extend(get_conferences(args, conference_group_html))
    return result


def get_relative_path(args, session):
    return f'MP3/{get_year_path(args, session.conference)}/{get_month_path(args, session.conference)}/{get_session_path(args, session)}'


def get_resource_path(relative_path):
    # Try to retrieve the PyInstaller resource path
    try:
        base_path = sys._MEIPASS
    except Exception:
        # Default to current directory if not found
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_session_path(args, session, nonumbers=False):
    if args.nonumbers or nonumbers:
        return f'{session.title}'
    else:
        return f'{session.number}-{session.title}'


def get_year_path(args, conference):
    return f'{conference.year}'


def gui_get_settings(args):
    lang_list = ["{} ({})".format(v, k) for k, v in args.lang_map.items()]
    lang_list_idx = "{} ({})".format(args.lang_map[args.lang], args.lang)
    year_list = range(1971, args.max_year+1)
    has_cache = os.path.exists(f'{args.cache_home}/{args.lang}')
    layout = [
        [sg.Text('_'  * 150, size=(80, 1))],
        [sg.Text('General Conference Selection', font=('Helvetica', 16))],
        [sg.Text("Language:", size=(25, 1), justification="right"), sg.OptionMenu(values=lang_list, default_value=lang_list_idx, key='-LANG-', size=(50,1))],
        [sg.Text("Starting year:", size=(25, 1), justification="right"), sg.OptionMenu(values=year_list, default_value=args.start, key='-START-', size=(50,1))],
        [sg.Text("Ending year:", size=(25, 1), justification="right"), sg.OptionMenu(values=year_list, default_value=args.end, key='-END-', size=(50,1))],
        [sg.Text('_'  * 150, size=(80, 1))],
        [sg.Text('Downloader Output Settings', font=('Helvetica', 16))],
        [sg.Text("Destination path:", size=(25, 1), justification="right"), sg.FolderBrowse(initial_folder=args.dest, target='-DEST-', size=(10,1)), sg.Text(args.dest, key='-DEST-', size=(40, 1))],
        [sg.Text("Minimum talks for speaker playlist:", size=(25, 1), justification="right"), sg.OptionMenu(values=range(1,10), default_value=args.speaker_min, key='-SPEAKER-MIN-', size=(50,1))],
        [sg.Text("No MP3 playlists:", size=(25, 1), justification="right"), sg.Checkbox(text="Skip creating MP3 playlist files?", default=args.noplaylists, key='-NOPLAYLISTS-')],
        [sg.Text("Add session Number:", size=(25, 1), justification="right"), sg.Checkbox(text="Order sessions by adding number prefix?", default=not args.nonumbers, key='-NONUMBERS-')],
        [sg.Text('_'  * 150, size=(80, 1))],
        [sg.Text('Other Settings', font=('Helvetica', 16))],
        [sg.Text("Delete Cached Talks:", size=(25, 1), justification="right"), sg.Checkbox(text="Speed up future downloads by keeping cache of talks?", default=args.nocleanup, key='-NOCLEANUP-')],
        [sg.Button('Start Download', key='-BEGIN-', size=(20,3), focus=True), sg.Exit(size=(10,3)), sg.Button('Delete Talks Cache', visible=has_cache, key='-DELETE-', size=(10,3))]
    ]
    window = sg.Window('General Conference Downloader', layout, finalize=True)
    while True:
        event, values = window.read()
        window['-DELETE-'].update(visible=os.path.exists(f'{args.cache_home}/{args.lang}'))
        if event == sg.WIN_CLOSED or event == 'Exit':
            window.close()
            sys.exit(0)
        elif event == '-DELETE-':
            remove_cached_files(args)
            window['-DELETE-'].update(visible=False)
        elif event == '-BEGIN-':
            args.lang = [k for k, v in args.lang_map.items() if values['-LANG-'].startswith(v)][0]
            args.start = int(values['-START-'])
            args.end = int(values['-END-'])
            if args.start > args.end:
                args.start, args.end = args.end, args.start
            args.dest = window['-DEST-'].TKStringVar.get()
            args.nocleanup = values['-NOCLEANUP-']
            args.nonumbers = not values['-NONUMBERS-']
            args.noplaylists = values['-NOPLAYLISTS-']
            args.speaker_min = int(values['-SPEAKER-MIN-'])
            break
    window.close()
    return args


def remove_cached_files(args):
    shutil.rmtree(f'{args.cache_home}/{args.lang}', ignore_errors=True)


def remove_playlist_files(file_pattern):
    for file in glob.glob(file_pattern):
        os.remove(file)


def update_playlists(args, playlists, talk, audio):
    year_path = get_year_path(args, talk.session.conference)
    month_path = get_month_path(args, talk.session.conference)
    session_path = get_session_path(args, talk.session, nonumbers=True)
    relative_path = get_relative_path(args, talk.session)
    duration = MP3(f'{get_output_dir(args)}/{relative_path}/{audio.file}').info.length

    # Add this talk to the year, conference, or session playlists
    playlists[f'Conferences/{year_path}'].append({'duration' : duration, 'path' : f'../{relative_path}/{audio.file}', 'title' : talk.title})
    playlists[f'Conferences/{year_path}-{month_path}'].append({'duration' : duration, 'path' : f'../{relative_path}/{audio.file}', 'title' : talk.title})
    playlists[f'Conferences/{year_path}-{month_path}-{session_path}'].append({'duration' : duration, 'path' : f'../{relative_path}/{audio.file}', 'title' : talk.title})

    # Add this talk to each topic playlist
    for topic in talk.topics:
        # Always do newest talks to oldest for topic playlists
        playlists[f'Topics/{topic}'].insert(0, {'duration' : duration, 'path' : f'../{relative_path}/{audio.file}', 'title' : talk.title})

    # If talk title says this is sustaining or church audit report, skip it for this speaker
    if -1 != talk.title.find("Sustaining of") or talk.title.startswith("Church Auditing"):
        return
    # Always do newest talks to oldest for speaker playlists
    playlists[f'Speakers/{talk.speaker}'].insert(0, {'duration' : duration, 'path' : f'../{relative_path}/{audio.file}', 'title' : talk.title, 'year': talk.session.conference.year})


def validate_args(args):
    args.lang_map = get_all_languages_map(args)
    if args.lang not in args.lang_map:
        sys.stderr.write(f'The given language ({args.lang}) is not available. Please choose one of the following:\n')
        for code in args.lang_map:
            sys.stderr.write(f'\t{args.lang_map[code]} = {code}\n')
        sys.exit(1)
    # Correct any odd start year numbers to be within range
    if args.start > args.max_year:
        args.start = args.max_year
    if args.start < args.min_year:
        args.start = args.min_year
    # Correct any odd end year numbers to be within range
    if args.end > args.max_year:
        args.end = args.max_year
    if args.end < args.min_year:
        args.end = args.min_year
    # Make sure start is always less than end
    if args.start > args.end:
        args.start, args.end = args.end, args.start


def write_playlist_file(args, playlist_path, playlist_data):
    # Remove any similar playlist file found first
    remove_playlist_files(f'{get_output_dir(args)}/{playlist_path}*.m3u')

    # If play list is empty return without creating a playlist
    if not playlist_data:
        return

    # If speaker playlist then check minimum talks limit before writing playlist
    first = playlist_data[0].get('year')
    last = playlist_data[-1].get('year')
    if not first or not last or len(playlist_data) >= args.speaker_min:
        count = len(playlist_data)
        playlist_info = get_playlist_info(first, last, count, sum(audio_info['duration'] for audio_info in playlist_data))
        # Now create new replacement playlist file
        file_path = f'{get_output_dir(args)}/{playlist_path}-({playlist_info}).m3u'
        if args.verbose:
            print("Writing playlist: {}".format(file_path))
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write("#EXTM3U\n\n")
            for audio_info in playlist_data:
                f.write(f"#EXTINF:{get_duration_text(audio_info['duration'])}, {audio_info['title']}\n")
                f.write(audio_info['path'].replace("/","\\"))
                f.write("\n\n")


def write_playlists(args, playlists):
    with tqdm(total=len(playlists.keys()), unit="playlists") as progress_bar:
        progress_bar.write("Writing playlists")
        for key, value in playlists.items():
            progress_bar.set_description_str(key+".m3u")
            write_playlist_file(args, key, value)
            progress_bar.update(1)
            if hasattr(progress_bar, 'running') and not progress_bar.running:
                break


def write_mp3_to_disk(data, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "wb") as f:
        f.write(data)


if __name__ == '__main__':
    min_year = 1971
    max_year = datetime.datetime.now().year
    user_home = pathlib.Path.home()
    cache_home = os.path.join(user_home, ".lds_gc_cache")
    music_home = os.path.join(user_home, "Music")
    parser = argparse.ArgumentParser(description='Download language specific LDS General Conference MP3s, '
                                                 'creating playlists for each conference, speaker and topic.')
    parser.add_argument('-lang',
                        help='Language version to download. See https://www.churchofjesuschrist.org/languages for full list.',
                        default='eng')
    parser.add_argument('-speaker-min', type=int,
                        help='Minimum talk count to have a playlist be created for a speaker',
                        default=3)
    parser.add_argument('-start', type=int,
                        help='First year to download. Note: not all historic sessions are available in all languages',
                        default=min_year)
    parser.add_argument('-end', type=int,
                        help='Last year to download (defaults to present year).',
                        default=max_year)
    parser.add_argument('-dest',
                        help='Destination folder to output files to.',
                        default=music_home)
    parser.add_argument('-nocleanup',
                        help='Leaves temporary files after process completion.',
                        action="store_true")
    parser.add_argument('-verbose',
                        help='Provides detailed activity logging instead of progress bars.',
                        action="store_true")
    parser.add_argument('-nonumbers',
                        help='Excludes generated session numbers from file and/or directory names.',
                        action="store_true")
    parser.add_argument('-noplaylists',
                        help='Skip creating m3u playlist files',
                        action="store_true")
    parser.add_argument('-nogui',
                        help='Use command line only for options and progress',
                        action="store_true")

    args = parser.parse_args()
    args.min_year = min_year
    args.max_year = max_year
    args.cache_home = cache_home
    validate_args(args)

    if CLI_ONLY or (len(sys.argv) > 1 and args.nogui):
        # Initialize colorama
        colorama.init()

        # Use dummy progress bar if verbose is enabled
        if args.verbose:
            tqdm = DummyTqdm
    else:
        # Use GUI progress bar
        tqdm = GuiTqdm

        # Give user a chance to change settings
        args = gui_get_settings(args)

    # Now download selected content
    download_all_content(args)
    sys.exit(0)
