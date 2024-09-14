import json
import os
import time
from pathlib import Path

import torch
from PySide6 import QtWidgets
from PySide6.QtCore import QUrl, QThread, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import QMessageBox

from videotrans import translator
from videotrans.component.component import DropButton
from videotrans.configure import config
from videotrans.recognition import FASTER_WHISPER, OPENAI_WHISPER, is_allow_lang, is_input_api
from videotrans.task._speech2text import SpeechToText
from videotrans.util import tools
from videotrans.winform import fn_downmodel


class SignThread(QThread):
    uito = Signal(str)

    def __init__(self, uuid_list=None, parent=None):
        super().__init__(parent=parent)
        self.uuid_list = uuid_list

    def post(self, jsondata):
        self.uito.emit(json.dumps(jsondata))

    def run(self):
        length = len(self.uuid_list)
        while 1:
            if len(self.uuid_list) == 0 or config.exit_soft:
                self.post({"type": "end"})
                time.sleep(1)
                return

            for uuid in self.uuid_list:
                if uuid in config.stoped_uuid_set:
                    try:
                        self.uuid_list.remove(uuid)
                    except:
                        pass
                    continue
                q = config.uuid_logs_queue.get(uuid)
                if not q:
                    continue
                try:
                    if q.empty():
                        time.sleep(0.5)
                        continue
                    data = q.get(block=False)
                    if not data:
                        continue
                    self.post(data)
                    if data['type'] in ['error', 'succeed']:
                        self.uuid_list.remove(uuid)
                        self.post({"type": "jindu", "text": f'{int((length - len(self.uuid_list)) * 100 / length)}%'})
                        config.stoped_uuid_set.add(uuid)
                        del config.uuid_logs_queue[uuid]
                except:
                    pass


def openwin():
    RESULT_DIR = config.HOME_DIR + f"/recogn"
    Path(RESULT_DIR).mkdir(exist_ok=True)

    def feed(d):
        if winobj.has_done:
            return
        if isinstance(d, str):
            d = json.loads(d)
        if d['type'] == 'replace':
            winobj.shibie_text.clear()
            winobj.shibie_text.setPlainText(d["text"])
        elif d['type'] == 'subtitle':
            winobj.shibie_text.moveCursor(QTextCursor.End)
            winobj.shibie_text.insertPlainText(d['text'])
        elif d['type'] == 'error':
            winobj.has_done = True
            winobj.loglabel.setText(d['text'][:120])
            winobj.loglabel.setStyleSheet("""color:#ff0000""")
            winobj.shibie_startbtn.setDisabled(False)
            winobj.shibie_startbtn.setText(config.box_lang["Start"])
        elif d['type'] == 'logs' and d['text']:
            winobj.loglabel.setText(d['text'])
        elif d['type'] in ['jindu', 'succeed']:
            winobj.loglabel.setStyleSheet('''color:#148cd2''')
            winobj.shibie_startbtn.setText(d['text'])
        elif d['type'] in ['end']:
            config.box_recogn = 'stop'
            winobj.has_done = True
            winobj.loglabel.setText(config.transobj['quanbuend'])
            winobj.shibie_startbtn.setText(config.transobj["zhixingwc"])
            winobj.shibie_startbtn.setDisabled(False)
            winobj.shibie_dropbtn.setText(config.transobj['quanbuend'] + ". " + config.transobj['xuanzeyinshipin'])

    def opendir_fn():
        QDesktopServices.openUrl(QUrl.fromLocalFile(RESULT_DIR))

    def shibie_start_fun():
        winobj.has_done = False
        config.settings = config.parse_init()
        model = winobj.shibie_model.currentText()
        split_type_index = winobj.shibie_split_type.currentIndex()
        recogn_type = winobj.shibie_recogn_type.currentIndex()

        langcode = translator.get_audio_code(show_source=winobj.shibie_language.currentText())

        is_cuda = winobj.is_cuda.isChecked()
        if check_cuda(is_cuda) is not True:
            return QMessageBox.critical(winobj, config.transobj['anerror'],
                                        config.transobj["nocudnn"])

        if recogn_type == FASTER_WHISPER and model.find('/') == -1:
            file = f'{config.ROOT_DIR}/models/models--Systran--faster-whisper-{model}/snapshots'
            if model.startswith('distil'):
                file = f'{config.ROOT_DIR}/models/models--Systran--faster-{model}/snapshots'
            if not os.path.exists(file):
                fn_downmodel.openwin(model_name=model, recogn_type=FASTER_WHISPER)
                return

        if recogn_type == OPENAI_WHISPER and not Path(config.ROOT_DIR + f'/models/{model}.pt').exists():
            fn_downmodel.openwin(model_name=model, recogn_type=OPENAI_WHISPER)
            return
        # 待识别音视频文件列表
        files = winobj.shibie_dropbtn.filelist
        if not files or len(files) < 1:
            return QMessageBox.critical(winobj, config.transobj['anerror'], config.transobj['bixuyinshipin'])

        is_allow_lang_res = is_allow_lang(langcode=langcode, recogn_type=recogn_type)
        if is_allow_lang_res is not True:
            return QMessageBox.critical(winobj, config.transobj['anerror'], is_allow_lang_res)
        # 判断是否填写自定义识别api openai-api识别、zh_recogn识别信息
        if is_input_api(recogn_type=recogn_type) is not True:
            return

        winobj.shibie_startbtn.setText(config.transobj["running"])
        winobj.label_shibie10.setText('')
        winobj.shibie_text.clear()

        winobj.shibie_opendir.setDisabled(False)
        try:
            winobj.shibie_startbtn.setDisabled(True)
            winobj.loglabel.setText('')
            config.box_recogn = 'ing'

            video_list = [tools.format_video(it, None) for it in files]
            uuid_list = [obj['uuid'] for obj in video_list]
            for it in video_list:
                trk = SpeechToText({
                    "recogn_type": recogn_type,
                    "split_type": ["all", "avg"][split_type_index],
                    "model_name": model,
                    "is_cuda": is_cuda,
                    "target_dir": RESULT_DIR,
                    "detect_language": langcode
                }, it)
                config.prepare_queue.append(trk)
            th = SignThread(uuid_list=uuid_list, parent=winobj)
            th.uito.connect(feed)
            th.start()

        except Exception as e:
            QMessageBox.critical(winobj, config.transobj['anerror'], str(e))

    def check_cuda(state):
        # 选中如果无效，则取消
        if state:
            if not torch.cuda.is_available():
                QMessageBox.critical(winobj, config.transobj['anerror'], config.transobj['nocuda'])
                winobj.is_cuda.setChecked(False)
                winobj.is_cuda.setDisabled(True)
                return False
            if winobj.shibie_recogn_type.currentIndex() == OPENAI_WHISPER:
                return True

            if winobj.shibie_recogn_type.currentIndex() == FASTER_WHISPER:
                from torch.backends import cudnn
                if not cudnn.is_available() or not cudnn.is_acceptable(torch.tensor(1.).cuda()):
                    QMessageBox.critical(winobj, config.transobj['anerror'], config.transobj["nocudnn"])
                    winobj.is_cuda.setChecked(False)
                    winobj.is_cuda.setDisabled(True)
                    return False
        return True

    # 设定模型类型
    def recogn_type_change():
        recogn_type = winobj.shibie_recogn_type.currentIndex()
        if recogn_type > 0:
            winobj.shibie_split_type.setDisabled(True)
        else:
            winobj.shibie_split_type.setDisabled(False)
        if recogn_type > 1:
            winobj.shibie_model.setDisabled(True)
        else:
            winobj.shibie_model.setDisabled(False)
        lang = translator.get_code(show_text=winobj.shibie_language.currentText())
        is_allow_lang_res = is_allow_lang(langcode=lang, recogn_type=config.params['recogn_type'])
        if is_allow_lang_res is not True:
            QMessageBox.critical(winobj, config.transobj['anerror'], is_allow_lang_res)

    from videotrans.component import Recognform
    try:
        winobj = config.child_forms.get('recognform')
        if winobj is not None:
            winobj.show()
            winobj.raise_()
            winobj.activateWindow()
            return

        winobj = Recognform()
        config.child_forms['recognform'] = winobj
        winobj.shibie_dropbtn = DropButton(config.transobj['xuanzeyinshipin'])
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(winobj.shibie_dropbtn.sizePolicy().hasHeightForWidth())
        winobj.shibie_dropbtn.setSizePolicy(sizePolicy)
        winobj.shibie_dropbtn.setMinimumSize(0, 150)
        winobj.shibie_widget.insertWidget(0, winobj.shibie_dropbtn)

        winobj.shibie_language.addItems(config.langnamelist)
        winobj.shibie_model.addItems(config.WHISPER_MODEL_LIST)
        winobj.shibie_startbtn.clicked.connect(shibie_start_fun)
        winobj.shibie_opendir.clicked.connect(opendir_fn)
        winobj.is_cuda.toggled.connect(check_cuda)
        winobj.shibie_recogn_type.currentIndexChanged.connect(recogn_type_change)

        winobj.show()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(e)