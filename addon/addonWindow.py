import os
import sys
import logging
import json
from copy import deepcopy
from tempfile import gettempdir

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QPlainTextEdit, QDialog, QListWidgetItem, QVBoxLayout, QPushButton
from PyQt5.QtCore import pyqtSlot, QThread, Qt

from .queryApi import apis
from .UIForm import wordGroup, mainUI, icons_rc
from .workers import LoginStateCheckWorker, VersionCheckWorker, RemoteWordFetchingWorker, QueryWorker, AudioDownloadWorker
from .dictionary import dictionaries
from .logger import Handler
from .loginDialog import LoginDialog
from .misc import Mask
from .constants import BASIC_OPTION, EXTRA_OPTION, MODEL_NAME, RELEASE_URL

try:
    from aqt import mw
    from aqt.utils import askUser, showCritical, showInfo, tooltip, openLink
    from .noteManager import getOrCreateDeck, getDeckList, getOrCreateModel, getOrCreateModelCardTemplate, addNoteToDeck, getWordsByDeck, getNotes
except ImportError:
    from test.dummy_aqt import mw, askUser, showCritical, showInfo, tooltip, openLink
    from test.dummy_noteManager import getOrCreateDeck, getDeckList, getOrCreateModel, getOrCreateModelCardTemplate, addNoteToDeck, getWordsByDeck, getNotes

logger = logging.getLogger('dict2Anki')


def fatal_error(exc_type, exc_value, exc_traceback):
    logger.exception(exc_value, exc_info=(exc_type, exc_value, exc_traceback))


# 未知異常日誌
sys.excepthook = fatal_error


class Windows(QDialog, mainUI.Ui_Dialog):
    isRunning = False

    def __init__(self, parent=None):
        super(Windows, self).__init__(parent)
        self.selectedDict = None
        self.currentConfig = dict()
        self.localWords = []
        self.selectedGroups = []

        self.workerThread = QThread(self)
        self.workerThread.start()
        self.updateCheckThead = QThread(self)
        self.updateCheckThead.start()
        self.audioDownloadThread = QThread(self)

        self.updateCheckWork = None
        self.loginWorker = None
        self.queryWorker = None
        self.pullWorker = None
        self.audioDownloadWorker = None

        self.setupUi(self)
        self.setWindowTitle(MODEL_NAME)
        self.setupLogger()
        self.initCore()
        self.checkUpdate()
        # self.__dev() # 以備調試時使用

    def __dev(self):
        def on_dev():
            logger.debug('whatever')

        self.devBtn = QPushButton('Magic Button', self.mainTab)
        self.devBtn.clicked.connect(on_dev)
        self.gridLayout_4.addWidget(self.devBtn, 4, 3, 1, 1)

    def closeEvent(self, event):
        # 插件關閉時退出所有線程
        if self.workerThread.isRunning():
            self.workerThread.requestInterruption()
            self.workerThread.quit()
            self.workerThread.wait()

        if self.updateCheckThead.isRunning():
            self.updateCheckThead.quit()
            self.updateCheckThead.wait()

        if self.audioDownloadThread.isRunning():
            self.audioDownloadThread.requestInterruption()
            self.workerThread.quit()
            self.workerThread.wait()

        event.accept()

    def setupLogger(self):
        """初始化 Logger """

        def onDestroyed():
            logger.removeHandler(QtHandler)

        # 防止 debug 信息寫入stdout/stderr 導致 Anki 崩潰
        logFile = os.path.join(gettempdir(), 'dict2anki.log')
        logging.basicConfig(handlers=[logging.FileHandler(logFile, 'w', 'utf-8')], level=logging.DEBUG, format='[%(asctime)s][%(levelname)8s] -- %(message)s - (%(name)s)')

        logTextBox = QPlainTextEdit(self)
        logTextBox.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout = QVBoxLayout()
        layout.addWidget(logTextBox)
        self.logTab.setLayout(layout)
        QtHandler = Handler(self)
        logger.addHandler(QtHandler)
        QtHandler.newRecord.connect(logTextBox.appendPlainText)

        # 日誌Widget銷燬時移除 Handlers
        logTextBox.destroyed.connect(onDestroyed)

    def setupGUIByConfig(self):
        config = mw.addonManager.getConfig(__name__)
        self.deckComboBox.setCurrentText(config['deck'])
        self.dictionaryComboBox.setCurrentIndex(config['selectedDict'])
        self.apiComboBox.setCurrentIndex(config['selectedApi'])
        self.usernameLineEdit.setText(config['credential'][config['selectedDict']]['username'])
        self.passwordLineEdit.setText(config['credential'][config['selectedDict']]['password'])
        self.cookieLineEdit.setText(config['credential'][config['selectedDict']]['cookie'])
        self.definitionCheckBox.setChecked(config['definition'])
        self.imageCheckBox.setChecked(config['image'])
        self.sentenceCheckBox.setChecked(config['sentence'])
        self.phraseCheckBox.setChecked(config['phrase'])
        self.AmEPhoneticCheckBox.setChecked(config['AmEPhonetic'])
        self.BrEPhoneticCheckBox.setChecked(config['BrEPhonetic'])
        self.BrEPronRadioButton.setChecked(config['BrEPron'])
        self.AmEPronRadioButton.setChecked(config['AmEPron'])
        self.noPronRadioButton.setChecked(config['noPron'])
        self.selectedGroups = config['selectedGroup']

    def initCore(self):
        self.usernameLineEdit.hide()
        self.usernameLabel.hide()
        self.passwordLabel.hide()
        self.passwordLineEdit.hide()
        self.dictionaryComboBox.addItems([d.name for d in dictionaries])
        self.apiComboBox.addItems([d.name for d in apis])
        self.deckComboBox.addItems(getDeckList())
        self.setupGUIByConfig()

    def getAndSaveCurrentConfig(self) -> dict:
        """獲取當前設置"""
        currentConfig = dict(
            selectedDict=self.dictionaryComboBox.currentIndex(),
            selectedApi=self.apiComboBox.currentIndex(),
            selectedGroup=self.selectedGroups,
            deck=self.deckComboBox.currentText(),
            username=self.usernameLineEdit.text(),
            password=Mask(self.passwordLineEdit.text()),
            cookie=Mask(self.cookieLineEdit.text()),
            definition=self.definitionCheckBox.isChecked(),
            sentence=self.sentenceCheckBox.isChecked(),
            image=self.imageCheckBox.isChecked(),
            phrase=self.phraseCheckBox.isChecked(),
            AmEPhonetic=self.AmEPhoneticCheckBox.isChecked(),
            BrEPhonetic=self.BrEPhoneticCheckBox.isChecked(),
            BrEPron=self.BrEPronRadioButton.isChecked(),
            AmEPron=self.AmEPronRadioButton.isChecked(),
            noPron=self.noPronRadioButton.isChecked(),
        )
        logger.info(f'當前設置:{currentConfig}')
        self._saveConfig(currentConfig)
        self.currentConfig = currentConfig
        return currentConfig

    @staticmethod
    def _saveConfig(config):
        _config = deepcopy(config)
        _config['credential'] = [dict(username='', password='', cookie='')] * len(dictionaries)
        _config['credential'][_config['selectedDict']] = dict(
            username=_config.pop('username'),
            password=str(_config.pop('password')),
            cookie=str(_config.pop('cookie'))
        )
        maskedConfig = deepcopy(_config)
        maskedCredential = [
            dict(
                username=c['username'],
                password=Mask(c['password']),
                cookie=Mask(c['cookie'])) for c in maskedConfig['credential']
        ]
        maskedConfig['credential'] = maskedCredential
        logger.info(f'保存配置項:{maskedConfig}')
        mw.addonManager.writeConfig(__name__, _config)

    def checkUpdate(self):
        @pyqtSlot(str, str)
        def on_haveNewVersion(version, changeLog):
            if askUser(f'有新版本:{version}是否更新？\n\n{changeLog.strip()}'):
                openLink(RELEASE_URL)

        self.updateCheckWork = VersionCheckWorker()
        self.updateCheckWork.moveToThread(self.updateCheckThead)
        self.updateCheckWork.haveNewVersion.connect(on_haveNewVersion)
        self.updateCheckWork.finished.connect(self.updateCheckThead.quit)
        self.updateCheckWork.start.connect(self.updateCheckWork.run)
        self.updateCheckWork.start.emit()

    @pyqtSlot(int)
    def on_dictionaryComboBox_currentIndexChanged(self, index):
        """詞典候選框改變事件"""
        self.currentDictionaryLabel.setText(f'當前選擇詞典: {self.dictionaryComboBox.currentText()}')
        config = mw.addonManager.getConfig(__name__)
        self.cookieLineEdit.setText(config['credential'][index]['cookie'])

    @pyqtSlot()
    def on_pullRemoteWordsBtn_clicked(self):
        """獲取單詞按鈕點擊事件"""
        if not self.deckComboBox.currentText():
            showInfo('\n請選擇或輸入要同步的牌組')
            return

        self.mainTab.setEnabled(False)
        self.progressBar.setValue(0)
        self.progressBar.setMaximum(0)

        currentConfig = self.getAndSaveCurrentConfig()
        self.selectedDict = dictionaries[currentConfig['selectedDict']]()

        # 登陸線程
        self.loginWorker = LoginStateCheckWorker(self.selectedDict.checkCookie, json.loads(self.cookieLineEdit.text() or '{}'))
        self.loginWorker.moveToThread(self.workerThread)
        self.loginWorker.start.connect(self.loginWorker.run)
        self.loginWorker.logSuccess.connect(self.onLogSuccess)
        self.loginWorker.logFailed.connect(self.onLoginFailed)
        self.loginWorker.start.emit()

    @pyqtSlot()
    def onLoginFailed(self):
        showCritical('第一次登錄或cookie失效!請重新登錄')
        self.progressBar.setValue(0)
        self.progressBar.setMaximum(1)
        self.mainTab.setEnabled(True)
        self.cookieLineEdit.clear()
        self.loginDialog = LoginDialog(
            loginUrl=self.selectedDict.loginUrl,
            loginCheckCallbackFn=self.selectedDict.loginCheckCallbackFn,
            parent=self
        )
        self.loginDialog.loginSucceed.connect(self.onLogSuccess)
        self.loginDialog.show()

    @pyqtSlot(str)
    def onLogSuccess(self, cookie):
        self.cookieLineEdit.setText(cookie)
        self.getAndSaveCurrentConfig()
        self.selectedDict.checkCookie(json.loads(cookie))
        self.selectedDict.getGroups()

        container = QDialog(self)
        group = wordGroup.Ui_Dialog()
        group.setupUi(container)

        for groupName in [str(group_name) for group_name, _ in self.selectedDict.groups]:
            item = QListWidgetItem()
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setText(groupName)
            item.setCheckState(Qt.Unchecked)
            group.wordGroupListWidget.addItem(item)

        # 恢復上次選擇的單詞本分組
        if self.selectedGroups:
            for groupName in self.selectedGroups[self.currentConfig['selectedDict']]:
                items = group.wordGroupListWidget.findItems(groupName, Qt.MatchExactly)
                for item in items:
                    item.setCheckState(Qt.Checked)
        else:
            self.selectedGroups = [list()] * len(dictionaries)

        def onAccepted():
            """選擇單詞本彈窗確定事件"""
            # 清空 listWidget
            self.newWordListWidget.clear()
            self.needDeleteWordListWidget.clear()
            self.mainTab.setEnabled(False)

            selectedGroups = [group.wordGroupListWidget.item(index).text() for index in range(group.wordGroupListWidget.count()) if
                              group.wordGroupListWidget.item(index).checkState() == Qt.Checked]
            # 保存分組記錄
            self.selectedGroups[self.currentConfig['selectedDict']] = selectedGroups
            self.progressBar.setValue(0)
            self.progressBar.setMaximum(1)
            logger.info(f'選中單詞本{selectedGroups}')
            self.getRemoteWordList(selectedGroups)

        def onRejected():
            """選擇單詞本彈窗取消事件"""
            self.progressBar.setValue(0)
            self.progressBar.setMaximum(1)
            self.mainTab.setEnabled(True)

        group.buttonBox.accepted.connect(onAccepted)
        group.buttonBox.rejected.connect(onRejected)
        container.exec()

    def getRemoteWordList(self, selected_groups: [str]):
        """根據選中到分組獲取分組下到全部單詞，並添加到 newWordListWidget"""
        group_map = dict(self.selectedDict.groups)
        self.localWords = getWordsByDeck(self.deckComboBox.currentText())

        # 啟動單詞獲取線程
        self.pullWorker = RemoteWordFetchingWorker(self.selectedDict, [(group_name, group_map[group_name],) for group_name in selected_groups])
        self.pullWorker.moveToThread(self.workerThread)
        self.pullWorker.start.connect(self.pullWorker.run)
        self.pullWorker.tick.connect(lambda: self.progressBar.setValue(self.progressBar.value() + 1))
        self.pullWorker.setProgress.connect(self.progressBar.setMaximum)
        self.pullWorker.doneThisGroup.connect(self.insertWordToListWidget)
        self.pullWorker.done.connect(self.on_allPullWork_done)
        self.pullWorker.start.emit()

    @pyqtSlot(list)
    def insertWordToListWidget(self, words: list):
        """一個分組獲取完畢事件"""
        for word in words:
            wordItem = QListWidgetItem(word, self.newWordListWidget)
            wordItem.setData(Qt.UserRole, None)
        self.newWordListWidget.clearSelection()

    @pyqtSlot()
    def on_allPullWork_done(self):
        """全部分組獲取完畢事件"""
        localWordList = set(getWordsByDeck(self.deckComboBox.currentText()))
        remoteWordList = set([self.newWordListWidget.item(row).text() for row in range(self.newWordListWidget.count())])

        newWords = remoteWordList - localWordList  # 新單詞
        needToDeleteWords = localWordList - remoteWordList  # 需要刪除的單詞
        logger.info(f'本地: {localWordList}')
        logger.info(f'遠程: {remoteWordList}')
        logger.info(f'待查: {newWords}')
        logger.info(f'待刪: {needToDeleteWords}')
        waitIcon = QIcon(':/icons/wait.png')
        delIcon = QIcon(':/icons/delete.png')
        self.newWordListWidget.clear()
        self.needDeleteWordListWidget.clear()

        for word in needToDeleteWords:
            item = QListWidgetItem(word)
            item.setCheckState(Qt.Checked)
            item.setIcon(delIcon)
            self.needDeleteWordListWidget.addItem(item)

        for word in newWords:
            item = QListWidgetItem(word)
            item.setIcon(waitIcon)
            self.newWordListWidget.addItem(item)
        self.newWordListWidget.clearSelection()

        self.dictionaryComboBox.setEnabled(True)
        self.apiComboBox.setEnabled(True)
        self.deckComboBox.setEnabled(True)
        self.pullRemoteWordsBtn.setEnabled(True)
        self.queryBtn.setEnabled(self.newWordListWidget.count() > 0)
        self.syncBtn.setEnabled(self.newWordListWidget.count() == 0 and self.needDeleteWordListWidget.count() > 0)
        if self.needDeleteWordListWidget.count() == self.newWordListWidget.count() == 0:
            logger.info('無需同步')
            tooltip('無需同步')
        self.mainTab.setEnabled(True)

    @pyqtSlot()
    def on_queryBtn_clicked(self):
        logger.info('點擊查詢按鈕')
        currentConfig = self.getAndSaveCurrentConfig()
        self.queryBtn.setEnabled(False)
        self.pullRemoteWordsBtn.setEnabled(False)
        self.syncBtn.setEnabled(False)

        wordList = []
        selectedWords = self.newWordListWidget.selectedItems()
        if selectedWords:
            # 如果選中單詞則只查詢選中的單詞
            for wordItem in selectedWords:
                wordBundle = dict()
                row = self.newWordListWidget.row(wordItem)
                wordBundle['term'] = wordItem.text()
                for configName in BASIC_OPTION + EXTRA_OPTION:
                    wordBundle[configName] = currentConfig[configName]
                    wordBundle['row'] = row
                wordList.append(wordBundle)
        else:  # 沒有選擇則查詢全部
            for row in range(self.newWordListWidget.count()):
                wordBundle = dict()
                wordItem = self.newWordListWidget.item(row)
                wordBundle['term'] = wordItem.text()
                for configName in BASIC_OPTION + EXTRA_OPTION:
                    wordBundle[configName] = currentConfig[configName]
                    wordBundle['row'] = row
                wordList.append(wordBundle)

        logger.info(f'待查詢單詞{wordList}')
        # 查詢線程
        self.progressBar.setMaximum(len(wordList))
        self.queryWorker = QueryWorker(wordList, apis[currentConfig['selectedApi']])
        self.queryWorker.moveToThread(self.workerThread)
        self.queryWorker.thisRowDone.connect(self.on_thisRowDone)
        self.queryWorker.thisRowFailed.connect(self.on_thisRowFailed)
        self.queryWorker.tick.connect(lambda: self.progressBar.setValue(self.progressBar.value() + 1))
        self.queryWorker.allQueryDone.connect(self.on_allQueryDone)
        self.queryWorker.start.connect(self.queryWorker.run)
        self.queryWorker.start.emit()

    @pyqtSlot(int, dict)
    def on_thisRowDone(self, row, result):
        """該行單詞查詢完畢"""
        doneIcon = QIcon(':/icons/done.png')
        wordItem = self.newWordListWidget.item(row)
        wordItem.setIcon(doneIcon)
        wordItem.setData(Qt.UserRole, result)

    @pyqtSlot(int)
    def on_thisRowFailed(self, row):
        failedIcon = QIcon(':/icons/failed.png')
        failedWordItem = self.newWordListWidget.item(row)
        failedWordItem.setIcon(failedIcon)

    @pyqtSlot()
    def on_allQueryDone(self):
        failed = []

        for i in range(self.newWordListWidget.count()):
            wordItem = self.newWordListWidget.item(i)
            if not wordItem.data(Qt.UserRole):
                failed.append(wordItem.text())

        if failed:
            logger.warning(f'查詢失敗或未查詢:{failed}')

        self.pullRemoteWordsBtn.setEnabled(True)
        self.queryBtn.setEnabled(True)
        self.syncBtn.setEnabled(True)

    @pyqtSlot()
    def on_syncBtn_clicked(self):

        failedGenerator = (self.newWordListWidget.item(row).data(Qt.UserRole) is None for row in range(self.newWordListWidget.count()))
        if any(failedGenerator):
            if not askUser('存在未查詢或失敗的單詞，確定要加入單詞本嗎？\n 你可以選擇失敗的單詞點擊 "查詢按鈕" 來重試。'):
                return

        currentConfig = self.getAndSaveCurrentConfig()
        model = getOrCreateModel(MODEL_NAME)
        if not mw.col.models.byName(MODEL_NAME):
            getOrCreateModelCardTemplate(model, 'Recognition')
            getOrCreateModelCardTemplate(model, 'Recall')
            getOrCreateModelCardTemplate(model, 'Sound')

            model['css'] = '''
            .card {
                font-family: arial;
                font-size: 20px;
                text-align: left;
                color: black;
                background-color: white;
            }
            .term {
                font-size : 35px;
            }
                '''
            mw.col.models.add(model)

        deck = getOrCreateDeck(self.deckComboBox.currentText(), model=model)

        logger.info('同步點擊')
        audiosDownloadTasks = []
        newWordCount = self.newWordListWidget.count()

        # 判斷是否需要下載發音
        # if currentConfig['noPron']:
        #     logger.info('不下載發音')
        #     whichPron = None
        # else:
        #     whichPron = 'AmEPron' if self.AmEPronRadioButton.isChecked() else 'BrEPron'
        #     logger.info(f'下載發音{whichPron}')

        added = 0
        media_path = mw.col.media._dir

        for row in range(newWordCount):
            wordItem = self.newWordListWidget.item(row)
            wordItemData = wordItem.data(Qt.UserRole)
            if wordItemData:
                addNoteToDeck(deck, model, currentConfig, wordItemData)
                added += 1
                # 添加發音任務
                if wordItemData.get('AmEPron'):
                    audiosDownloadTasks.append(
                        (f"{media_path}/AmEPron_{wordItemData['term']}.mp3", wordItemData['AmEPron'],))
                if wordItemData.get('BrEPron'):
                    audiosDownloadTasks.append(
                        (f"{media_path}/BrEPron_{wordItemData['term']}.mp3", wordItemData['BrEPron'],))

                # elif whichPron and wordItemData.get(whichPron):
                #     audiosDownloadTasks.append((f"{whichPron}_{wordItemData['term']}.mp3", wordItemData[whichPron],))


        logger.info(f'collection path {mw.col.path}')
        logger.info(f'現在位置 {os.getcwd()}')
        logger.info(f'{mw.col.media}')

        # mw.col.name()
        # (media_dir, media_db) = media_paths_from_col_path(self.path)
        mw.reset()

        logger.info(f'發音下載任務:{audiosDownloadTasks}')

        if audiosDownloadTasks:
            self.syncBtn.setEnabled(False)
            self.progressBar.setValue(0)
            self.progressBar.setMaximum(len(audiosDownloadTasks))
            if self.audioDownloadThread is not None:
                self.audioDownloadThread.requestInterruption()
                self.audioDownloadThread.quit()
                self.audioDownloadThread.wait()

            self.audioDownloadThread = QThread(self)
            self.audioDownloadThread.start()
            self.audioDownloadWorker = AudioDownloadWorker(audiosDownloadTasks)
            self.audioDownloadWorker.moveToThread(self.audioDownloadThread)
            self.audioDownloadWorker.tick.connect(lambda: self.progressBar.setValue(self.progressBar.value() + 1))
            self.audioDownloadWorker.start.connect(self.audioDownloadWorker.run)
            self.audioDownloadWorker.done.connect(lambda: tooltip(f'發音下載完成'))
            self.audioDownloadWorker.done.connect(self.audioDownloadThread.quit)
            self.audioDownloadWorker.start.emit()

        self.newWordListWidget.clear()

        needToDeleteWordItems = [
            self.needDeleteWordListWidget.item(row)
            for row in range(self.needDeleteWordListWidget.count())
            if self.needDeleteWordListWidget.item(row).checkState() == Qt.Checked
        ]
        needToDeleteWords = [i.text() for i in needToDeleteWordItems]

        deleted = 0

        if needToDeleteWords and askUser(f'確定要刪除這些單詞嗎:{needToDeleteWords[:3]}...({len(needToDeleteWords)}個)', title='Dict2Anki', parent=self):
            needToDeleteWordNoteIds = getNotes(needToDeleteWords, currentConfig['deck'])
            mw.col.remNotes(needToDeleteWordNoteIds)
            deleted += 1
            mw.col.reset()
            mw.reset()
            for item in needToDeleteWordItems:
                self.needDeleteWordListWidget.takeItem(self.needDeleteWordListWidget.row(item))
            logger.info('刪除完成')
        logger.info('完成')

        if not audiosDownloadTasks:
            tooltip(f'添加{added}個筆記\n刪除{deleted}個筆記')
