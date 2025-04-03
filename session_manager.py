import requests
import json
import time
import logging
from os.path import expanduser
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    filename='wq_session.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class SessionManager:
    """管理 WorldQuant Brain API 会话的类"""
    
    def __init__(self, credentials_file='brain_credentials.txt'):
        """初始化会话管理器"""
        self.credentials_file = expanduser(credentials_file)
        self.username, self.password = self._load_credentials()
        self.session = None
        self.session_created_at = None
        self.session_valid_duration = timedelta(hours=3.5)  # 设置为比4小时稍短的时间
        self.create_session()
    
    def _load_credentials(self):
        """从文件加载凭据"""
        try:
            with open(self.credentials_file) as f:
                credentials = json.load(f)
            return credentials[0], credentials[1]
        except Exception as e:
            logging.error(f"Failed to load credentials: {str(e)}")
            raise
    
    def create_session(self):
        """创建新的会话"""
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(self.username, self.password)
        
        response = self.session.post('https://api.worldquantbrain.com/authentication')
        
        if response.status_code in [200,201]:
            self.session_created_at = datetime.now()
            logging.info("Session created successfully")
            print("Session created successfully")
        else:
            logging.error(f"Failed to create session: {response.status_code}, {response.text}")
            raise Exception(f"Authentication failed: {response.status_code}")
        
        return self.session
    
    def get_session(self):
        """获取有效的会话，如果即将过期则刷新"""
        if self.session is None or self._is_session_expiring():
            self.create_session()
        return self.session
    
    def _is_session_expiring(self):
        """检查会话是否即将过期"""
        if self.session_created_at is None:
            return True
        
        time_elapsed = datetime.now() - self.session_created_at
        return time_elapsed > self.session_valid_duration
    
    def post(self, url, **kwargs):
        """发送 POST 请求"""
        session = self.get_session()
        response = session.post(url, **kwargs)
        return response
    
    def get(self, url, **kwargs):
        """发送 GET 请求"""
        session = self.get_session()
        response = session.get(url, **kwargs)
        return response

    def request_with_retry(self, method, url, max_retries=3, **kwargs):
        """发送请求，自动处理会话过期"""
        retries = 0
        while retries < max_retries:
            try:
                session = self.get_session()
                if method.lower() == 'get':
                    response = session.get(url, **kwargs)
                elif method.lower() == 'post':
                    response = session.post(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                # 检查是否是认证错误
                if response.status_code == 401:
                    logging.warning("Session expired, creating new session")
                    self.create_session()
                    retries += 1
                    continue
                
                return response
            
            except Exception as e:
                logging.error(f"Request failed: {str(e)}")
                retries += 1
                if retries < max_retries:
                    logging.info(f"Retrying ({retries}/{max_retries})...")
                    time.sleep(5)  # 稍等片刻再重试
                    self.create_session()  # 创建新会话后重试
                else:
                    logging.error("Max retries reached")
                    raise