VERSION = 'v1'
RELEASE_URL = 'https://github.com/megachweng/Dict2Anki'
VERSION_CHECK_API = 'https://api.github.com/repos/megachweng/Dict2Anki/releases/latest'
MODEL_NAME = f'Dict2Anki-guofoo-{VERSION}'

BASIC_OPTION = ['definition', 'sentence', 'phrase', 'image', 'BrEPhonetic', 'AmEPhonetic']  # 順序和名稱不可修改
EXTRA_OPTION = ['BrEPron', 'AmEPron', 'noPron']  # 順序和名稱不可修改

MODEL_FIELDS = ['term', 'definition', 'sentence', 'phrase', 'image', 'BrEPhonetic', 'AmEPhonetic', 'BrEPron', 'AmEPron']  # 名稱不可修改