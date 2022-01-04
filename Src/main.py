import os
import random
import sqlite3
import sys
import time
from datetime import datetime
from typing import Dict

import requests

from Logger import getLogger
from Post import CPost
from Util import headers_raw_to_dict, readCookies, rasieACall, sp_user


class WeiboDog:
    
    def __init__(self):
        self.logger = getLogger()
        self.mainSession = requests.session()
        self.conn = sqlite3.connect("history.db")
        self.header: Dict[str, str]
        self.header = headers_raw_to_dict(b'''
        accept: application/json, text/plain, */*
accept-encoding: gzip, deflate, br
accept-language: zh-CN,zh;q=0.9
cookie: %b
mweibo-pwa: 1
referer: https://m.weibo.cn/
sec-ch-ua: " Not A;Brand";v="99", "Chromium";v="96", "Google Chrome";v="96"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
sec-fetch-dest: empty
sec-fetch-mode: cors
sec-fetch-site: same-origin
user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36
x-requested-with: XMLHttpRequest
x-xsrf-token: 1d1b9c
        ''' % readCookies())

        self.cookies = self.header["cookie"]
        self.thisPagePost: Dict[int, CPost] = {}
        self.thisRecommendPagePost: Dict[int, CPost] = {}
        self.st, self.uid = self.get_st()

        self.initConn()
    
    def initConn(self):
        cursor = self.conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS history(
   mid VARCHAR(20),
   PRIMARY KEY(mid)
);''')
        cursor.close()
        self.conn.commit()

    def updateHistory(self, mid: int) -> Dict[str, str]:
        cursor = self.conn.cursor()
        cursor.execute(f'''
        insert into history (mid) values ({mid});
        ''')
        cursor.close()
        self.conn.commit()
        self.logger.info(f"转发{mid}历史存库成功")

    def isInHistory(self, mid: int) -> bool:
    
        cursor = self.conn.cursor()
        cursor.execute(f'''
        select * from history where mid = {mid};
        ''')
    
        values = cursor.fetchall()
        cursor.close()
        return len(values) > 0

    def get_header(self) -> Dict[str, str]:
        return self.header

    def add_header_param(self, key: str, value: str) -> Dict[str, str]:
        header = self.get_header()
        header[key] = value
        return header

    def add_ref(self, value: str) -> Dict[str, str]:
        return self.add_header_param("referer", value)
    
    def get_st(self) -> tuple[str, int]:  # st是转发微博post必须的参数
        url = "https://m.weibo.cn/api/config"
        header = self.add_ref(url)
        r = self.mainSession.get(url, headers=header)
        data = r.json()
        isLogin = data['data']['login']
        if not isLogin:
            raise Exception("未登录")
        st = data["data"]["st"]
        uid = int(data['data']['uid'])
        return st, uid
    
    def refeshToken(self):
        st, _ = self.get_st()
        self.header["x-xsrf-token"] = st
        return self.header
    
    def refreshPage(self):
        '''
        刷新主页
        '''
        st, _ = self.get_st()
        url = "https://m.weibo.cn/feed/friends?"
        header = self.add_ref("https://m.weibo.cn/")
        self.header["x-xsrf-token"] = st
        r = self.mainSession.get(url, headers=header)
        data = r.json()
        self.thisPagePost = {}
        try:
            if r.json().get("ok") == 1:
                for dPost in data["data"]["statuses"]:
                    _oPost = CPost(dPost)
                    self.thisPagePost[_oPost.uid] = _oPost
                return True
            else:
                self.logger.error(f"刷新主页失败 err = {data}")
                return False
        except Exception as e:
            self.logger.error(data)
            self.logger.error(e)
            time.sleep(30)
            self.refreshPage()

    def refreshRecommend(self):
        st, _ = self.get_st()
        url = "https://m.weibo.cn/api/container/getIndex?containerid=102803&openApp=0"
        header = self.add_ref("https://m.weibo.cn/")
        self.header["x-xsrf-token"] = st
        r = self.mainSession.get(url, headers=header)
        data = r.json()
        self.thisRecommendPagePost = {}
        try:
            if r.json().get("ok") == 1:
                for dPost in data["data"]["cards"]:
                    _oPost = CPost(dPost["mblog"], isRecommend=True)
                    self.thisRecommendPagePost[_oPost.uid] = _oPost
                return True
            else:
                self.logger.error(f"刷新热门失败 err = {data}")
                return False
        except Exception as e:
            self.logger.error(data)
            self.logger.error(e)
            time.sleep(60)
            self.refreshRecommend()

    def like(self, oPost: CPost) -> bool:
        st, _ = self.get_st()
        mid = oPost.uid
        url = "https://m.weibo.cn/api/attitudes/create"
        data = {"id": mid, "attitude": "heart", "st": st, "_spr": "screen:2560x1440"}
        self.add_ref(f"https://m.weibo.cn")
        self.header["x-xsrf-token"] = st
        r = self.mainSession.post(url, data=data, headers=self.header)
        try:
            if r.json().get("ok") == 1:
                self.logger.info(f'点赞{mid}成功')
                return True
            else:
                self.logger.error(f'点赞{mid}失败')
                return False
        except Exception as e:
            self.logger.error(r.json())
            self.logger.error(e)

    def repost(self, oPost: CPost):
        st, _ = self.get_st()
        url = "https://m.weibo.cn/api/statuses/repost"
        content = "转发微博"
        mid = oPost.uid
        if self.isInHistory(mid):
            return False
        if oPost.onlyFans:
            self.logger.info(f"微博{mid} 仅粉丝可见，不可转载")
            self.updateHistory(mid)
            self.dump_post(oPost)
            return False
        data = {"id": mid, "content": content, "mid": mid, "st": st, "_spr": "screen:2560x1440"}
        # 这里一定要加referer， 不加会变成不合法的请求
        self.add_ref(f"https://m.weibo.cn/compose/repost?id={mid}")
        self.header["x-xsrf-token"] = st
        r = self.mainSession.post(url, data=data, headers=self.header)
        try:
            if r.json().get("ok") == 1:
                self.logger.info(
                    f'转发微博 userid = {oPost.userUid} name = {oPost.userName} mid = {oPost.uid} {"来自推荐" if oPost.isOriginPost() else ""} 成功')
                self.updateHistory(mid)
                self.like(oPost)
                self.dump_post(oPost)
                self.logger.info(f'保存微博{mid}成功')
                time.sleep(30)
                return True
            else:
                err = r.json()
                error_type = err["error_type"]
                errno = err["errno"]
                self.logger.error(
                    f'转发微博 userid = {oPost.userUid} name = {oPost.userName} mid = {oPost.uid} 失败 \n {err["msg"]} \n {r.json()}')
                rasieACall(f'转发微博{mid}失败 {err["msg"]}')
                if error_type == "captcha":
                    sys.exit(-1)
                elif errno == '20016':
                    time.sleep(60)
                else:
                    time.sleep(30)
                return False

        except Exception as e:
            self.logger.error(r.text)
            self.logger.error(e)

    def update_detail(self, oPost: CPost) -> bool:
        mid = oPost.uid
        url = f"https://m.weibo.cn/statuses/extend?id={mid}"
        st, _ = self.get_st()
        self.add_ref(f"https://m.weibo.cn/status/{mid}")
        self.header["x-xsrf-token"] = st
        r = self.mainSession.get(url, headers=self.header)
        responseJson = r.json()
        try:
            if responseJson.get("ok") == 1:
                self.logger.info(f'更新{mid}全文成功')
                oPost.text = responseJson["data"]["longTextContent"]
                return True
            else:
                self.logger.error(f'更新{mid}全文失败')
                return False
        except Exception as e:
            self.logger.error(responseJson)
            self.logger.error(e)

    def __del__(self):
        self.mainSession.close()
        handlers = self.logger.handlers[:]
        for handler in handlers:
            handler.close()
            self.logger.removeHandler(handler)
        self.conn.close()

    def dump_post(self, oPost: CPost):
        '''
        保存微博文章和图片 todo 异步下载
        '''
        rootPath = f"Data/{oPost.userUid}/{oPost.uid}"
        if not os.path.exists(rootPath):
            os.makedirs(rootPath)
        contextName = f"{rootPath}/{oPost.uid}.txt"
        if oPost.Text().find("全文") > 0:
            self.update_detail(oPost)
        with open(contextName, 'w', encoding="utf8") as f:
            f.write(f"{oPost.userName}\n")
            f.write(f"{oPost.createdTime}\n")
            f.write(oPost.Text() + '\n')
            for livePhoto in oPost.livePhotos:
                f.write(livePhoto + '\n')
            if oPost.video:
                f.write(oPost.video)

        self.logger.info(f"保存微博 mid = {oPost.uid} 内容成功")

        for idx, image in enumerate(oPost.images):
            try:
                imageName = image.split('/').pop()
                res = requests.get(image)
                with open(f"{rootPath}/{imageName}", 'wb') as f:
                    f.write(res.content)
            except Exception as e:
                self.logger.error(e)
            self.logger.info(f"保存微博{oPost.uid}图片{idx + 1}成功")


if __name__ == '__main__':
    wd = WeiboDog()
    rasieACall("启动成功")
    while 1:
        try:
            if 2 <= datetime.now().hour < 6:
                wd.logger.info("Heartbeat without request")
                time.sleep(60)
                continue
            wd.refreshPage()
            time.sleep(5)
            wd.refreshRecommend()
            iterDict = {**wd.thisRecommendPagePost, **wd.thisPagePost}
            for oPost in iterDict.values():
                if oPost.isOriginPost() and len(oPost.images) >= 3:
                    wd.repost(oPost)
                elif oPost.isOriginPost() and oPost.video:
                    wd.repost(oPost)
                elif not oPost.isOriginPost():
                    lSp = sp_user()  # 只转发别人微博的博主
                    if oPost.userUid in lSp:
                        if len(oPost.originPost.images) >= 3 or oPost.originPost.video:
                            wd.repost(oPost.originPost)
            interval = random.randint(50, 60)
            wd.logger.info("Heartbeat")
            time.sleep(interval)
        except Exception as e:
            wd.logger.error(e)
            rasieACall(e)
