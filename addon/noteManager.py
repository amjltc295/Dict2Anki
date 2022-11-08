from .constants import MODEL_FIELDS, BASIC_OPTION, EXTRA_OPTION
import logging

logger = logging.getLogger('dict2Anki.noteManager')
try:
    from aqt import mw
    import anki
except ImportError:
    from test.dummy_aqt import mw
    from test import dummy_anki as anki


def getDeckList():
    return [deck['name'] for deck in mw.col.decks.all()]


def getWordsByDeck(deckName) -> [str]:
    notes = mw.col.findNotes(f'deck:"{deckName}"')
    words = []
    for nid in notes:
        note = mw.col.getNote(nid)
        if note.model().get('name', '').lower().startswith('dict2anki') and note['term']:
            words.append(note['term'])
    return words


def getNotes(wordList, deckName) -> list:
    notes = []
    for word in wordList:
        note = mw.col.findNotes(f'deck:"{deckName}" term:"{word}"')
        if note:
            notes.append(note[0])
    return notes


def getOrCreateDeck(deckName, model):
    deck_id = mw.col.decks.id(deckName)
    deck = mw.col.decks.get(deck_id)
    mw.col.decks.select(deck['id'])
    mw.col.decks.save(deck)
    mw.col.models.setCurrent(model)
    model['did'] = deck['id']
    mw.col.models.save(model)
    mw.col.reset()
    mw.reset()
    return deck


def getOrCreateModel(modelName):
    model = mw.col.models.byName(modelName)
    if model:
        if set([f['name'] for f in model['flds']]) == set(MODEL_FIELDS):
            return model
        else:
            logger.warning('模版字段異常，自動刪除重建')
            mw.col.models.rem(model)

    logger.info(f'創建新模版:{modelName}')
    newModel = mw.col.models.new(modelName)
    for field in MODEL_FIELDS:
        mw.col.models.addField(newModel, mw.col.models.newField(field))
    return newModel


CARDS = {'Recognition': {}, 'Recall': {}, 'Sound': {}}
CARDS['Recognition']['qfmt'] = '''
<table>
    <tr>
        <td><h1 class="term">{{term}}</h1><br><div> UK [{{BrEPhonetic}}] US [{{AmEPhonetic}}]</div></div></td>
    </tr>
</table>
<hr>
Definition：
<div>Tap to View</div>
<hr>
Phrases：
<p>{{phrase}}</p>
<hr>
Sentences：
<p>{{sentence}}</p>
{{AmEPron}}

<script>
document.querySelectorAll("span.ch").forEach(e => e.remove());
examples.querySelectorAll("b").forEach(e => e.innerText = '[...]');
</script>
'''

CARDS['Recognition']['afmt'] = '''
<table>
    <tr>
        <td><h1 class="term">{{term}}</h1><br><div> UK [{{BrEPhonetic}}] US [{{AmEPhonetic}}]</div></div></td>
        <td><img {{image}} height="120px"></td>
    </tr>
</table>
<hr>
Definition：
<div>{{definition}}</div>
<hr>
Phrases：
<p>{{phrase}}</p>
<hr>
Sentences：
<p>{{sentence}}</p>
'''


CARDS['Recall']['qfmt'] = '''
<table>
    <tr>
        <td><img {{image}} height="120px"></td>
    </tr>
</table>
<hr>
Definition：
<div>{{definition}}</div>
<hr>
Phrases：
<p>{{phrase}}</p>
<hr>

<script>
document.querySelectorAll("b").forEach(e => e.innerText = '[...]');
</script>

'''

CARDS['Recall']['afmt'] = '''
<table>
    <tr>
        <td><h1 class="term">{{term}}</h1><br><div> UK [{{BrEPhonetic}}] US [{{AmEPhonetic}}]</div></div></td>
        <td><img {{image}} height="120px"></td>
    </tr>
</table>
<hr>
Definition：
<div>Tap to View</div>
<hr>
Phrases：
<p>{{phrase}}</p>
<hr>
Sentences：
<p>{{sentence}}</p>
{{AmEPron}}
'''
CARDS['Sound']['qfmt'] = '''
{{AmEPron}}'''

CARDS['Sound']['afmt'] = '''
<table>
    <tr>
        <td><h1 class="term">{{term}}</h1><br><div> UK [{{BrEPhonetic}}] US [{{AmEPhonetic}}]</div></div></td>
        <td><img {{image}} height="120px"></td>
    </tr>
</table>
<hr>
Definition：
<div>{{definition}}</div>
<hr>
Phrases：
<p>{{phrase}}</p>
<hr>
Sentences：
<p>{{sentence}}</p>
{{AmEPron}}
'''


def getOrCreateModelCardTemplate(modelObject, cardTemplateName):
    logger.info(f'添加卡片類型:{cardTemplateName}')
    existingCardTemplate = modelObject['tmpls']
    if cardTemplateName in [t.get('name') for t in existingCardTemplate]:
        return
    cardTemplate = mw.col.models.newTemplate(cardTemplateName)
    cardTemplate['qfmt'] = CARDS[cardTemplateName]['qfmt']
    cardTemplate['afmt'] = CARDS[cardTemplateName]['afmt']

    mw.col.models.addTemplate(modelObject, cardTemplate)


def addNoteToDeck(deckObject, modelObject, currentConfig: dict, oneQueryResult: dict):
    if not oneQueryResult:
        logger.warning(f'查詢結果{oneQueryResult} 異常，忽略')
        return
    modelObject['did'] = deckObject['id']

    newNote = anki.notes.Note(mw.col, modelObject)
    term = newNote['term'] = oneQueryResult['term']
    for configName in BASIC_OPTION + EXTRA_OPTION:
        logger.debug(f'字段:{configName}--結果:{oneQueryResult.get(configName)}')
        if oneQueryResult.get(configName):
            # Sentences and phrases
            if configName in ['sentence', 'phrase'] and currentConfig[configName]:
                es = []
                cs = []
                for e, c in oneQueryResult[configName]:
                    e = e.strip().replace(term, f'<b>{term}</b>')
                    c = c.strip()
                    es.append(f'<span class="en">{e}</span>')
                    cs.append(f'<span class="ch">{c}</span>')

                newNote[configName] = '\n'.join(
                    [f'<p>{e}<br>\n{c}</p>'
                     for e, c in zip(es, cs)])
            # Image
            elif configName == 'image':
                newNote[configName] = f'src="{oneQueryResult[configName]}"'
            # Definition
            elif configName == 'definition' and currentConfig[configName]:
                newNote[configName] = '<br>'.join(oneQueryResult[configName])
            # Pronunciation
            elif configName in EXTRA_OPTION[:2]:
                newNote[configName] = f"[sound:{configName}_{oneQueryResult['term']}.mp3]"
            # Others
            elif currentConfig[configName]:
                newNote[configName] = oneQueryResult[configName]

    mw.col.addNote(newNote)
    mw.col.reset()
    logger.info(f"添加筆記{newNote['term']}")
