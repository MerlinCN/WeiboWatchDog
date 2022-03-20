import time
import traceback

from Engine import SpiderEngine
from Util import barkCall, readSpecialUsers

if __name__ == '__main__':
    wd = SpiderEngine(loggerName="MainLoop")
    barkCall("启动成功")
    while 1:
        try:
            wd.refreshPage()
            iStartTime = time.time()
            for _oPost in wd.thisPagePost.values():
                if _oPost.isOriginPost():
                    isInScanHistory = wd.isInScanHistory(_oPost.uid)
                    if isInScanHistory:  # 单次扫描
                        continue
                    else:
                        wd.updateScanHistory(_oPost.uid)
                    if _oPost.liveLink():  # 带直播链接的不转发
                        continue
                    if _oPost.video and _oPost.isRecommend is False:  # 现在只点赞视频
                        wd.startRepost(_oPost)  # 现在只点赞视频
                    elif _oPost.specialTopics():
                        wd.startRepost(_oPost)
                    elif wd.detection(_oPost):  # 检测到图片中有人且大小满足
                        wd.startRepost(_oPost)
                else:  # 如果不是原创微博
                    lSp = readSpecialUsers()  # 只转发别人微博的博主
                    if _oPost.userUid not in lSp:
                        continue
                    isInScanHistory = wd.isInScanHistory(_oPost.originPost.uid)
                    if isInScanHistory:  # 单次扫描
                        continue
                    else:
                        wd.updateScanHistory(_oPost.originPost.uid)
                    if wd.detection(_oPost.originPost) or _oPost.originPost.video:
                        wd.startRepost(_oPost.originPost)
            iGap = time.time() - iStartTime
            if iGap <= 60:
                interval = 60 - iGap
            else:
                interval = 0
            wd.logger.info("Heartbeat")
            time.sleep(interval)
        except Exception as e:
            wd.logger.error(traceback.format_exc())
            barkCall(e)
