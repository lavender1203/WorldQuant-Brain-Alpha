"""WorldQuant Brain API 批量处理模块"""

import json
import os
from datetime import datetime
from os.path import expanduser
from time import sleep
import concurrent.futures  # 添加线程池支持
import threading  # 添加线程锁支持

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from tqdm import tqdm  # 导入tqdm库

from alpha_strategy import AlphaStrategy
from dataset_config import get_api_settings, get_dataset_config
from session_manager import SessionManager


class BrainBatchAlpha:
    API_BASE_URL = 'https://api.worldquantbrain.com'

    def __init__(self, credentials_file='brain_credentials.txt'):
        """初始化 API 客户端"""

        self.session = SessionManager()
        self.print_lock = threading.Lock()  # 添加线程锁防止输出混乱
        # self._setup_authentication(credentials_file)

    def _setup_authentication(self, credentials_file):
        """设置认证"""

        try:
            with open(expanduser(credentials_file)) as f:
                credentials = json.load(f)
            username, password = credentials
            self.session.auth = HTTPBasicAuth(username, password)

            response = self.session.post(f"{self.API_BASE_URL}/authentication")
            if response.status_code not in [200, 201]:
                raise Exception(f"认证失败: HTTP {response.status_code}")

            print("✅ 认证成功!")

        except Exception as e:
            print(f"❌ 认证错误: {str(e)}")
            raise

    def _simulate_single_alpha(self, alpha, alpha_index, total_pbar_position):
        """模拟单个 Alpha"""
        try:
            with self.print_lock:
                print(f"表达式: {alpha.get('regular', 'Unknown')}")

            # 发送模拟请求
            sim_resp = self.session.post(
                f"{self.API_BASE_URL}/simulations",
                json=alpha
            )

            if sim_resp.status_code != 201:
                with self.print_lock:
                    print(f"❌ 模拟请求失败 (状态码: {sim_resp.status_code})")
                return None

            try:
                sim_progress_url = sim_resp.headers['Location']
                start_time = datetime.now()

                # 创建本地进度条，使用 position 参数确保每个进度条固定位置
                pbar = tqdm(
                    total=100,
                    desc=f"Alpha {alpha_index}: 模拟进度",
                    position=total_pbar_position + alpha_index,
                    bar_format='{desc}: {percentage:3.0f}%|{bar}| {elapsed} 秒',
                    leave=False
                )
                last_progress = 0

                while True:
                    sim_progress_resp = self.session.get(sim_progress_url)
                    retry_after_sec = float(sim_progress_resp.headers.get("Retry-After", 0))

                    if retry_after_sec == 0:  # simulation done!
                        # 完成进度条
                        if last_progress < 100:
                            pbar.update(100 - last_progress)
                        pbar.close()

                        alpha_id = sim_progress_resp.json()['alpha']
                        with self.print_lock:
                            print(f"✅ 获得 Alpha ID: {alpha_id}")

                        # 等待一下让指标计算完成
                        sleep(3)

                        # 获取 Alpha 详情
                        alpha_url = f"{self.API_BASE_URL}/alphas/{alpha_id}"
                        alpha_detail = self.session.get(alpha_url)
                        alpha_data = alpha_detail.json()

                        # 检查是否有 is 字段
                        if 'is' not in alpha_data:
                            with self.print_lock:
                                print("❌ 无法获取指标数据")
                            return None

                        is_qualified = self.check_alpha_qualification(alpha_data)

                        return {
                            'expression': alpha.get('regular'),
                            'alpha_id': alpha_id,
                            'passed_all_checks': is_qualified,
                            'metrics': alpha_data.get('is', {}),
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }

                    # 更新等待时间和进度
                    elapsed = (datetime.now() - start_time).total_seconds()
                    # 假设通常需要 30 秒完成
                    current_progress = min(95, int((elapsed / 30) * 100))

                    # 只在进度变化时更新进度条
                    if current_progress > last_progress:
                        pbar.update(current_progress - last_progress)
                        last_progress = current_progress

                    sleep(retry_after_sec)

            except KeyError:
                with self.print_lock:
                    print("❌ 无法获取模拟进度 URL")
                return None

        except Exception as e:
            with self.print_lock:
                print(f"⚠️ Alpha 模拟失败: {str(e)}")
            return None


    def simulate_alphas(self, datafields=None, strategy_mode=1, dataset_name=None, max_workers=1):
       """并行模拟多个 Alpha 表达式"""

       try:
           datafields = self._get_datafields_if_none(datafields, dataset_name)
           if not datafields:
               return []

           alpha_list = self._generate_alpha_list(datafields, strategy_mode)
           if not alpha_list:
               return []

           print(f"\n🚀 开始并行模拟 {len(alpha_list)} 个 Alpha 表达式 (最大 {max_workers} 个线程)...")

           results = []
           results_lock = threading.Lock()  # 用于保护结果列表的线程锁

           # 使用线程池执行模拟任务
           with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
               # 创建任务到线程池
               futures = {
                   executor.submit(self._simulate_single_alpha, alpha, i, 1): i
                   for i, alpha in enumerate(alpha_list, 1)
               }

               # 创建总进度条，固定在最底部
               with tqdm(total=len(alpha_list), desc="🔄 总体进度", unit="alpha", position=0) as total_pbar:
                   # 处理完成的任务
                   for future in concurrent.futures.as_completed(futures):
                       alpha_index = futures[future]
                       try:
                           result = future.result()

                           with self.print_lock:
                               print(f"\n[{alpha_index}/{len(alpha_list)}] Alpha 模拟完成")

                           if result and result.get('passed_all_checks'):
                               with results_lock:
                                   results.append(result)
                                   self._save_alpha_id(result['alpha_id'], result)
                       except Exception as exc:
                           with self.print_lock:
                               print(f"\n[{alpha_index}/{len(alpha_list)}] Alpha 模拟失败: {exc}")

                       # 更新总进度条
                       total_pbar.update(1)

           return results

       except Exception as e:
           print(f"❌ 模拟过程出错: {str(e)}")
           return []
    # 修改 check_alpha_qualification 方法以支持线程安全
    def check_alpha_qualification(self, alpha_data):
        """检查 Alpha 是否满足所有提交条件"""

        try:
            # 从 'is' 字段获取指标
            is_data = alpha_data.get('is', {})
            if not is_data:
                with self.print_lock:
                    print("❌ 无法获取指标数据")
                return False

            # 获取指标值
            sharpe = float(is_data.get('sharpe', 0))
            fitness = float(is_data.get('fitness', 0))
            turnover = float(is_data.get('turnover', 0))
            ic_mean = float(is_data.get('margin', 0))  # margin 对应 IC Mean

            # 获取子宇宙 Sharpe
            sub_universe_check = next(
                (
                    check for check in is_data.get('checks', [])
                    if check['name'] == 'LOW_SUB_UNIVERSE_SHARPE'
                ),
                {}
            )
            subuniverse_sharpe = float(sub_universe_check.get('value', 0))
            required_subuniverse_sharpe = float(sub_universe_check.get('limit', 0))

            # 保护输出，防止多线程输出混乱
            with self.print_lock:
                # 打印指标
                print("\n📊 Alpha 指标详情:")
                print(f"  Sharpe: {sharpe:.3f} (>1.5)")
                print(f"  Fitness: {fitness:.3f} (>1.0)")
                print(f"  Turnover: {turnover:.3f} (0.1-0.9)")
                print(f"  IC Mean: {ic_mean:.3f} (>0.02)")
                print(f"  子宇宙 Sharpe: {subuniverse_sharpe:.3f} (>{required_subuniverse_sharpe:.3f})")

                print("\n📝 指标评估结果:")

            # 检查每个指标并输出结果
            is_qualified = True

            with self.print_lock:
                if sharpe < 1.5:
                    print("❌ Sharpe ratio 不达标")
                    is_qualified = False
                else:
                    print("✅ Sharpe ratio 达标")

                if fitness < 1.0:
                    print("❌ Fitness 不达标")
                    is_qualified = False
                else:
                    print("✅ Fitness 达标")

                if turnover < 0.1 or turnover > 0.9:
                    print("❌ Turnover 不在合理范围")
                    is_qualified = False
                else:
                    print("✅ Turnover 达标")

                if ic_mean < 0.02:
                    print("❌ IC Mean 不达标")
                    is_qualified = False
                else:
                    print("✅ IC Mean 达标")

                if subuniverse_sharpe < required_subuniverse_sharpe:
                    print(f"❌ 子宇宙 Sharpe 不达标 ({subuniverse_sharpe:.3f} < {required_subuniverse_sharpe:.3f})")
                    is_qualified = False
                else:
                    print(f"✅ 子宇宙 Sharpe 达标 ({subuniverse_sharpe:.3f} > {required_subuniverse_sharpe:.3f})")

                print("\n🔍 检查项结果:")
                checks = is_data.get('checks', [])
                for check in checks:
                    name = check.get('name')
                    result = check.get('result')
                    value = check.get('value', 'N/A')
                    limit = check.get('limit', 'N/A')

                    if result == 'PASS':
                        print(f"✅ {name}: {value} (限制: {limit})")
                    elif result == 'FAIL':
                        print(f"❌ {name}: {value} (限制: {limit})")
                        is_qualified = False
                    elif result == 'PENDING':
                        print(f"⚠️ {name}: 检查尚未完成")
                        is_qualified = False

                print("\n📋 最终评判:")
                if is_qualified:
                    print("✅ Alpha 满足所有条件，可以提交!")
                else:
                    print("❌ Alpha 未达到提交标准")

            return is_qualified

        except Exception as e:
            with self.print_lock:
                print(f"❌ 检查 Alpha 资格时出错: {str(e)}")
            return False
            
    # 还需要确保其他被线程调用的方法也是线程安全的
    def _save_alpha_id(self, alpha_id, result):
        """保存 Alpha ID 到文件"""
        try:
            # 确保目录存在
            os.makedirs('results', exist_ok=True)
            
            # 使用线程锁保护文件写入
            with self.print_lock:
                # 保存到 CSV 文件
                df = pd.DataFrame([result])
                file_exists = os.path.isfile('results/qualified_alphas.csv')
                df.to_csv('results/qualified_alphas.csv', mode='a', header=not file_exists, index=False)
                
                # 单独保存 ID 便于后续操作
                with open('results/alpha_ids.txt', 'a') as f:
                    f.write(f"{alpha_id}\n")
                    
                print(f"✅ Alpha ID {alpha_id} 已保存")
        except Exception as e:
            with self.print_lock:
                print(f"❌ 保存 Alpha ID 失败: {str(e)}")

    def submit_alpha(self, alpha_id):
        """提交单个 Alpha"""

        submit_url = f"{self.API_BASE_URL}/alphas/{alpha_id}/submit"

        for attempt in range(5):
            print(f"🔄 第 {attempt + 1} 次尝试提交 Alpha {alpha_id}")

            # POST 请求
            res = self.session.post(submit_url)
            if res.status_code == 201:
                print("✅ POST: 成功，等待提交完成...")
            elif res.status_code in [400, 403]:
                print(f"❌ 提交被拒绝 ({res.status_code})")
                return False
            else:
                sleep(3)
                continue

            # 检查提交状态
            while True:
                res = self.session.get(submit_url)
                retry = float(res.headers.get('Retry-After', 0))

                if retry == 0:
                    if res.status_code == 200:
                        print("✅ 提交成功!")
                        return True
                    return False

                sleep(retry)

        return False

    def submit_multiple_alphas(self, alpha_ids):
        """批量提交 Alpha"""
        successful = []
        failed = []

        for alpha_id in alpha_ids:
            if self.submit_alpha(alpha_id):
                successful.append(alpha_id)
            else:
                failed.append(alpha_id)

            if alpha_id != alpha_ids[-1]:
                sleep(10)

        return successful, failed

    def _get_datafields_if_none(self, datafields=None, dataset_name=None):
        """获取数据字段列表"""

        try:
            if datafields is not None:
                return datafields

            if dataset_name is None:
                print("❌ 未指定数据集")
                return None

            config = get_dataset_config(dataset_name)
            if not config:
                print(f"❌ 无效的数据集: {dataset_name}")
                return None

            # 获取数据字段
            search_scope = {
                'instrumentType': 'EQUITY',
                'region': 'USA',
                'delay': '1',
                'universe': config['universe']
            }

            url_template = (
                f"{self.API_BASE_URL}/data-fields?"
                f"instrumentType={search_scope['instrumentType']}"
                f"&region={search_scope['region']}"
                f"&delay={search_scope['delay']}"
                f"&universe={search_scope['universe']}"
                f"&dataset.id={config['id']}"
                "&limit=50&offset={offset}"
            )

            # 获取总数
            initial_resp = self.session.get(url_template.format(offset=0))
            if initial_resp.status_code != 200:
                print("❌ 获取数据字段失败")
                return None

            total_count = initial_resp.json()['count']

            # 获取所有数据字段
            all_fields = []
            for offset in range(0, total_count, 50):
                resp = self.session.get(url_template.format(offset=offset))
                if resp.status_code != 200:
                    continue
                all_fields.extend(resp.json()['results'])

            # 过滤矩阵类型字段
            matrix_fields = [
                field['id'] for field in all_fields
                if field.get('type') == 'MATRIX'
            ]

            if not matrix_fields:
                print("❌ 未找到可用的数据字段")
                return None

            print(f"✅ 获取到 {len(matrix_fields)} 个数据字段")
            return matrix_fields

        except Exception as e:
            print(f"❌ 获取数据字段时出错: {str(e)}")
            return None

    def _generate_alpha_list(self, datafields, strategy_mode):
        """生成 Alpha 表达式列表"""
        try:
            # 初始化策略生成器
            strategy_generator = AlphaStrategy()

            # 生成策略列表
            strategies = strategy_generator.get_simulation_data(datafields, strategy_mode)

            print(f"生成了 {len(strategies)} 个Alpha表达式")

            # 转换为 API 所需的格式
            alpha_list = []
            for strategy in strategies:
                simulation_data = {
                    'type': 'REGULAR',
                    'settings': {
                        'instrumentType': 'EQUITY',
                        'region': 'USA',
                        'universe': 'TOP3000',
                        'delay': 1,
                        'decay': 0,
                        'neutralization': 'SUBINDUSTRY',
                        'truncation': 0.08,
                        'pasteurization': 'ON',
                        'unitHandling': 'VERIFY',
                        'nanHandling': 'ON',
                        'language': 'FASTEXPR',
                        'visualization': False,
                    },
                    'regular': strategy
                }
                alpha_list.append(simulation_data)

            return alpha_list

        except Exception as e:
            print(f"❌ 生成 Alpha 列表失败: {str(e)}")
            return []
