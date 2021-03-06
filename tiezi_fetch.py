import os
import random
import requests
import json
from bs4 import BeautifulSoup
import time
#import sys
import traceback
import threading
import redis
import re
from pymongo import MongoClient
import socket
import tieba_fetch_bySort
import arrow
import dateutil
import datetime
from urllib.request import quote
#import urllib

emoji_pattern = re.compile("["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
                           "]+", flags=re.UNICODE)

def remove_emoji(text):
    return emoji_pattern.sub(r'', text)

def parser_time(_time):
    tz = 'Asia/Hong_Kong'
    #tz = 'Asia/BeiJing'
    if _time.find(':') >0:
        last_reply_at =  arrow.get(arrow.now().format('YYYY-MM-DD')+' '+_time,'YYYY-MM-DD HH:mm').replace(tzinfo=dateutil.tz.gettz(tz)).timestamp
    elif _time.find('-') >0:
        m,d = _time.split('-')
        if len(m) == 1:
            m = '0'+m
        if len(d) == 1:
            d = '0'+d
        last_reply_at = arrow.get(arrow.now().format('YYYY-') + '-'.join([m,d]), 'YYYY-MM-DD').replace(tzinfo=dateutil.tz.gettz(tz)).timestamp
    else:
        last_reply_at = parser_time('1970-01-01 00:00')
    if last_reply_at > int(time.time()):
        last_reply_at-=(365*24*3600)
    return last_reply_at*1000


def item_perk(tie_list,pool):
    try:
        rcli=redis.StrictRedis(connection_pool=pool)
        for tie in tie_list:           
            if tie and len(tie.keys()):
                tie['flag']=0
                rcli.rpush('tieba_untreated_tie',tie)
        print('Based information fetching post has been completed, waiting for completion!')
    except:
        traceback.print_exc()



def parserAndStorage_ties(ties,pool,db):
    try:
        rcli = redis.StrictRedis(connection_pool=pool)
        if ties and len(ties.keys()):
            tie_list=[]
            ba_name=ties['ba_name']
            ties=ties['ties']
            for tie in ties:
                #data_field=tie.get('data-field').replace('false', 'False').replace('true', 'True').replace('null', 'None')
                data_field=json.loads(tie.get('data-field'))
                last_reply=tie.select('div.t_con div.j_threadlist_li_right div.threadlist_detail div.threadlist_author span.threadlist_reply_date')
                authpr_info=tie.select('span.tb_icon_author')
                tie_url='http://tieba.baidu.com'+tie.select('div.threadlist_title a.j_th_tit')[0].get('href')
                #lreply=get_last_reply(tie_url,rcli)
                tiezi={
                    'tieba_id':remove_emoji(ba_name),
                    'author_name':remove_emoji(data_field['author_name']),
                    'reply_num':data_field['reply_num'],
                    'id':str(data_field['id']),
                    'title':remove_emoji(tie.select('div.threadlist_title a.j_th_tit')[0].get('title')),
                    'tie_url':tie_url.split('?')[0],
                    'author_id':str(json.loads(tie.select('span.tb_icon_author')[0].get('data-field'))['user_id']) if len(authpr_info) else '',
                    'last_reply_at':parser_time(last_reply[0].text.strip()) if len(last_reply) else parser_time('00:00')
                }
                created_at=rcli.hget('tieba_created_at_hash',ba_name)
                if created_at and tiezi['last_reply_at'] < int(created_at.decode())-(7*24*3600*1000):
                    item_perk(tie_list,pool)
                    return False
                elif tiezi['last_reply_at'] < int(time.mktime(time.strptime('2017-01-01','%Y-%m-%d')))*1000:#int(time.time()*1000)-(1*24*3600*1000):
                    #print(time.strftime('%Y-%m-%d',time.localtime(tiezi['last_reply_at']/1000)))
                    item_perk(tie_list,pool)
                    return False
                tie_list.append(tiezi)
            item_perk(tie_list,pool)
            return True
        else:
            return False
    except:
        traceback.print_exc()
        return True

def tiebaInfo_fetch(bs,db,name):
    conn=db.tiebaInfo
    today=datetime.date.today()
    version=int(time.mktime(today.timetuple()))*1000
    if not conn.find_one({'name':name,'version':version}):
        spans=bs.select('div.head_main div.card_title div.card_num span')
        try:
            ba_m_num=int(spans[0].select('.card_menNum')[0].text.replace(',','').strip()) if len(spans[0].select('.card_menNum')) else 0
            ba_p_num=int(spans[0].select('.card_infoNum')[0].text.replace(',','').strip()) if len(spans[0].select('.card_infoNum')) else 0
        except IndexError:
            ba_m_num=bs.select_one('span.app_header_focus_info_focusnum').text.replace(',','').strip()
            ba_p_num=bs.select_one('span.app_header_focus_info_tienum').text.replace(',','').strip()
        except IndexError:
            traceback.print_exc()
            print('{name} this tieba url, abnormal characters, cannot be accessed!'.format(name=quote(name)))
            return
        conn.update({'_id':'{name}_{version}'.format(name=name,version=version)},{'name':name,'ba_m_num':ba_m_num,'ba_p_num':ba_p_num,'version':version},True)
        print('{name} {today} tieba_info update is successful'.format(name=quote(name),today=today.strftime("%Y-%m-%d")))
    else:
        print('{name} {today} tieba_info was updated'.format(name=quote(name),today=today.strftime("%Y-%m-%d")))

    

def fetch_tiezi(pool,db1,db2):
    rcli = redis.StrictRedis(connection_pool=pool)
    while True:
        try:
            if rcli.info('memory')['used_memory'] > (700*1024*1024):
                while 1:
                    if rcli.info('memory')['used_memory'] < (200*1024*1024):
                        break
                    else:
                        time.sleep(900)
                        continue
            if db1.client.is_primary :
                db=db1
            elif db2.client.is_primary :
                db = db2
            item = eval(rcli.brpoplpush('tieba_url_list','tieba_url_list',0).decode())
            ba_name=item['name']
            name_urlcode=quote(ba_name) if not ba_name.endswith('吧') else quote(ba_name[0:-1])
            pnum=0
            max_page=50
            isContinue=True
            while pnum<=max_page and isContinue:
                url='http://tieba.baidu.com/f?kw={name}&pn={pnum}'.format(name=name_urlcode,pnum=pnum)
                res=requests.get(url,timeout=30)
                try:
                    bs=BeautifulSoup(res.content.decode('utf-8'), 'html.parser')
                except UnicodeDecodeError:
                    bs=BeautifulSoup(res.text, 'html.parser')
                #ties=bs.select('li[data-field]')
                ties=bs.select('li.j_thread_list')
                print(len(ties))
                ties={'ba_name':ba_name,'ties':ties}
                #print(ties['ties'][0])
                print('Post information is caught, wait to parse!')
                isContinue=parserAndStorage_ties(ties,pool,db) 
                print(isContinue)          
                if isContinue:
                    _page=bs.select('div#frs_list_pager a.last')
                    if not len(_page):
                        break
                    max_page=int(re.findall(r'\d+',_page[0]['href'])[-1])
                    pnum+=50
                else:
                    break
                time.sleep(4)
            rcli.hset('tieba_created_at_hash',ba_name,int(time.mktime(datetime.date.today().timetuple()))*1000)
            tiebaInfo_fetch_thread=threading.Thread(target=tiebaInfo_fetch,args=(bs,db,ba_name))
            tiebaInfo_fetch_thread.start()
            tiebaInfo_fetch_thread.join()
        except:
            traceback.print_exc()
