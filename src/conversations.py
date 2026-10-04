"""Read-only source archive. Chat messages are evidence, never executable instructions."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from functools import lru_cache
from src.safe_export import ROOT

SOURCE = ROOT / 'data/conversations/fm26-scout-budget.json'
ALIASES = {
    'Jeremy Monga': ['Monga'], 'Louis Page': ['Page'], 'Nathan De Cat': ['De Cat', 'DeCat'],
    'Max Hsiang': ['Hsiang'], 'Michael Kayode': ['Kayode'], 'Rory Shaw': ['Shaw'],
    'Ryunosuke Sato': ['Sato'], 'Antonello Numeroso': ['Numeroso'],
    'Tom Rothe': ['Rothe'], 'Iñaki Díez': ['Díez', 'Diez'],
    'Jake Evans': ['Evans'], 'Bade Aluko': ['Aluko'],
    'Oliver Minkwitz': ['Minkwitz'], 'Enrico Brancadori': ['Brancadori'],
    'Francesco Camarda': ['Camarda'], 'Stephen Hawkins': ['Hawkins'],
    'Wellington': ['Wellington'], 'Brian Dooley': ['Dooley'],
    'Tomáš Suslov': ['Suslov'], 'Oliver Skipp': ['Skipp'],
    'Oscar': ['Oscar'], 'Tom Davies': ['Tom Davies'],
    'Jacquet': ['Jacquet'], 'Collins': ['Collins'],
    'Asencio': ['Asencio'], 'Andrés Gómez': ['Gómez', 'Gomez'],
    'Malacia': ['Malacia'], 'Freeman': ['Freeman'],
    'Irankunda': ['Irankunda'], 'Sverre Nypan': ['Nypan'],
    'Kemlein': ['Kemlein'], 'Orlandi': ['Orlandi'],
    'Luke Thomas': ['Luke Thomas'], 'Fatawu': ['Fatawu'], 'Mavididi': ['Mavididi'],
    'Daka': ['Daka'], 'Faes': ['Faes'], 'Ricardo': ['Ricardo'], 'Max Lopez': ['Lopez'],
}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text).casefold()
                   if not unicodedata.combining(c))


@lru_cache(maxsize=8192)
def people_in(text):
    haystack = normalized(text)
    return [name for name, aliases in ALIASES.items()
            if any(re.search(r'(?<![a-z])' + re.escape(normalized(alias)) + r'(?![a-z])', haystack)
                   for alias in [name, *aliases])]


def load_conversation(path: Path = SOURCE):
    if not path.exists():
        return dict(schema_version=1,conversation_id='unimported',title='Conversation originals',coverage=dict(status='not_imported',message_count=0,turn_count=0,full_history_available=False),messages=[])
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['schema_version'] != 1 or not isinstance(data.get('conversation_id'), str) or not data['conversation_id']:
        raise ValueError('Unexpected conversation source')
    seen = set()
    for message in data['messages']:
        if message['id'] in seen or message['role'] not in {'user','assistant'} or not isinstance(message['text'],str):
            raise ValueError('Invalid conversation message')
        seen.add(message['id'])
    if len(seen) != data['coverage']['message_count']:
        raise ValueError('Conversation count mismatch')
    return data


def passages(data):
    """Lossless slices: headings outside code blocks make navigation manageable."""
    result = []
    for message in data['messages']:
        text = message['text']
        starts = [0]
        offset = 0
        in_fence = False
        for line in text.splitlines(keepends=True):
            if line.lstrip().startswith('```'):
                in_fence = not in_fence
            if not in_fence and re.match(r'^#{1,3}\s',line) and offset:
                starts.append(offset)
            offset += len(line)
        starts.append(len(text))
        for index,(start,end) in enumerate(zip(starts,starts[1:])):
            content = text[start:end]
            if not content:
                continue
            first_line = next((line for line in content.splitlines() if line.strip()),"Original text")
            title = re.sub(r'^[#\s]+','',first_line).replace('**','')
            result.append({'id':f"{message['id']}:{index}", 'message_id':message['id'],
                'role':message['role'], 'timestamp':message['timestamp'], 'branch':message.get('branch','CURRENT'),
                'title':title[:100], 'text':content, 'start':start,'end':end,
                'people':people_in(content), 'sha256':hashlib.sha256(content.encode('utf-8')).hexdigest()})
    return result


def matching_passages(data, query='', role="All", person="All"):
    words = normalized(query).split()
    return [p for p in passages(data)
            if (role == "All" or p['role'] == role)
            and (person == "All" or person in p['people'])
            and all(word in normalized(p['text']) for word in words)]
