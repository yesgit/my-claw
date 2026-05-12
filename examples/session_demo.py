#!/usr/bin/env python
"""会话级任务管理 CLI 示例

演示如何使用 Session API 创建会话、发起多个任务、查询结果。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 将上级目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.memory.conversation_store import ConversationStore


def main() -> None:
    """演示会话管理的基本流程"""
    
    # 初始化存储
    store = ConversationStore()
    
    print("=" * 60)
    print("MyClaw 会话级任务管理 CLI 示例")
    print("=" * 60)
    
    # 创建会话
    print("\n[1] 创建会话...")
    session_id = store.create_session(
        name="数据分析任务",
        config={
            "providerId": "openai-local",
            "modelId": "gpt-4.1-mini",
            "maxSteps": 8,
            "filesystemAllowedDirs": ["/tmp", "/home"],
        },
    )
    print(f"✓ 会话已创建: {session_id}")
    
    # 获取会话详情
    print("\n[2] 获取会话详情...")
    session = store.get_session(session_id)
    print(f"会话名称: {session['name']}")
    print(f"创建时间: {session['created_at']}")
    print(f"配置: {json.dumps(session['config'], ensure_ascii=False, indent=2)}")
    
    # 创建第一个任务
    print("\n[3] 创建第一个任务...")
    task1_id = store.create_task(
        session_id=session_id,
        goal="读取数据文件并进行初步分析",
    )
    print(f"✓ 任务1已创建: {task1_id}")
    
    # 模拟任务1完成
    print("\n[4] 模拟任务1执行和保存结果...")
    store.save_task(
        task_id=task1_id,
        status="completed",
        final_answer="数据文件包含1000条记录，时间范围为2026年1月至5月",
        steps=[
            {"step": 1, "action": "read_file", "file": "data.csv"},
            {"step": 2, "action": "analyze", "result": "data loaded"},
        ],
        duration_ms=2500,
    )
    print("✓ 任务1已完成")
    
    # 创建第二个任务
    print("\n[5] 创建第二个任务...")
    task2_id = store.create_task(
        session_id=session_id,
        goal="生成数据分析报告并保存到文件",
    )
    print(f"✓ 任务2已创建: {task2_id}")
    
    # 模拟任务2完成
    print("\n[6] 模拟任务2执行和保存结果...")
    store.save_task(
        task_id=task2_id,
        status="completed",
        final_answer="报告已生成: /tmp/analysis_report.md",
        steps=[
            {"step": 1, "action": "generate_report"},
            {"step": 2, "action": "write_file", "file": "analysis_report.md"},
        ],
        duration_ms=1800,
    )
    print("✓ 任务2已完成")
    
    # 列出会话内的所有任务
    print("\n[7] 列出会话内的所有任务...")
    tasks = store.list_tasks(session_id=session_id)
    for i, task in enumerate(tasks, 1):
        print(f"  任务{i}: {task['goal']}")
        print(f"    - 状态: {task['status']}")
        print(f"    - 结果: {task['final_answer']}")
        print(f"    - 耗时: {task['duration_ms']}ms")
        print(f"    - 步骤数: {len(task['steps'])}")
    
    # 列出所有会话
    print("\n[8] 列出所有会话...")
    all_sessions = store.list_sessions()
    for session in all_sessions:
        print(f"  - {session['name']} (ID: {session['id']})")
        print(f"    - 任务数: {session['task_count']}")
        print(f"    - 创建时间: {session['created_at']}")
    
    # 获取单个任务详情
    print(f"\n[9] 获取任务1的详细信息...")
    task = store.get_task(task1_id)
    print(f"任务目标: {task['goal']}")
    print(f"执行步骤:")
    for step in task['steps']:
        print(f"  - {step}")
    
    # 更新会话配置
    print("\n[10] 更新会话配置...")
    success = store.update_session_config(
        session_id,
        {
            "providerId": "openai-local",
            "modelId": "gpt-4.1-mini",
            "maxSteps": 12,  # 增加最大步骤数
            "filesystemAllowedDirs": ["/tmp", "/home"],
        },
    )
    if success:
        updated = store.get_session(session_id)
        print(f"✓ 配置已更新，maxSteps: {updated['config']['maxSteps']}")
    
    print("\n" + "=" * 60)
    print("演示完成！会话数据已存储到 SQLite 数据库")
    print("=" * 60)


if __name__ == "__main__":
    main()
