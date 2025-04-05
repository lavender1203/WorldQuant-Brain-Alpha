"""WorldQuant Brain 批量 Alpha 生成系统"""

import os

from brain_batch_alpha import BrainBatchAlpha
from dataset_config import get_dataset_by_index, get_dataset_list

STORAGE_ALPHA_ID_PATH = "alpha_ids.txt"


def submit_alpha_ids(brain, num_to_submit=2):
    """提交保存的 Alpha ID"""
    try:
        if not os.path.exists(STORAGE_ALPHA_ID_PATH):
            print("❌ 没有找到保存的Alpha ID文件")
            return

        with open(STORAGE_ALPHA_ID_PATH, 'r') as f:
            alpha_ids = [line.strip() for line in f.readlines() if line.strip()]

        if not alpha_ids:
            print("❌ 没有可提交的Alpha ID")
            return

        print("\n📝 已保存的Alpha ID列表:")
        for i, alpha_id in enumerate(alpha_ids, 1):
            print(f"{i}. {alpha_id}")

        if num_to_submit > len(alpha_ids):
            num_to_submit = len(alpha_ids)

        selected_ids = alpha_ids[:num_to_submit]
        successful, failed = brain.submit_multiple_alphas(selected_ids)

        # 更新 alpha_ids.txt
        remaining_ids = [id for id in alpha_ids if id not in successful]
        with open(STORAGE_ALPHA_ID_PATH, 'w') as f:
            f.writelines([f"{id}\n" for id in remaining_ids])

    except Exception as e:
        print(f"❌ 提交 Alpha 时出错: {str(e)}")


def main():
    """主程序入口"""
    try:
        print("🚀 启动 WorldQuant Brain 批量 Alpha 生成系统")

        # 固定模式为 2（仅测试模式）
        mode = 2
        print(f"🚀 选择的模式: {mode}")

        brain = BrainBatchAlpha()

        if mode in [1, 2]:
            print("\n📊 遍历所有可用数据集:")
            datasets = get_dataset_list()
            if not datasets:
                print("❌ 没有可用的数据集")
                return

            for index, _ in enumerate(datasets):
                dataset_name = get_dataset_by_index(index)
                if not dataset_name:
                    print(f"❌ 无效的数据集索引: {index}")
                    continue
                print(f"\n📋 当前数据集: {dataset_name}")

                print("\n📈 遍历所有策略模式:")
                for strategy_mode in [1, 2]:
                    print(f"🔄 当前策略模式: {strategy_mode}")

                    # 模拟 Alphas
                    results = brain.simulate_alphas(None, strategy_mode, dataset_name)
                    print(f"✅ 数据集 {dataset_name} 策略模式 {strategy_mode} 模拟完成，共生成 {len(results)} 个结果")

    except Exception as e:
        print(f"❌ 程序运行出错: {str(e)}")


if __name__ == "__main__":
    main()