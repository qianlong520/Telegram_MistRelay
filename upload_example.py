#!/usr/bin/env python3
"""
上传追踪表使用示例
==================

本文件演示如何使用 uploads 表来追踪上传任务，并区分下载失败和代码错误。
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db


def example_1_create_upload():
    """示例1：创建上传任务"""
    print("=" * 60)
    print("示例1：创建上传任务")
    print("=" * 60)
    
    # 假设已有一个下载任务 ID
    download_id = 1
    
    # 创建上传到 OneDrive 的任务
    upload_id = db.create_upload(
        download_id=download_id,
        upload_target='onedrive',
        remote_path='/videos/example.mp4',
        max_retries=3
    )
    
    print(f"✓ 创建上传任务成功，ID: {upload_id}")
    return upload_id


def example_2_upload_success_flow(upload_id):
    """示例2：上传成功流程"""
    print("\n" + "=" * 60)
    print("示例2：上传成功流程")
    print("=" * 60)
    
    # 1. 标记开始上传
    db.mark_upload_started(upload_id)
    print(f"✓ 开始上传，ID: {upload_id}")
    
    # 2. 更新上传进度
    db.update_upload_status(
        upload_id,
        status='uploading',
        uploaded_size=1024000,
        upload_speed=102400,
        total_size=10240000
    )
    print(f"✓ 更新进度: 1MB / 10MB (速度: 100KB/s)")
    
    # 3. 标记上传完成
    db.mark_upload_completed(upload_id, remote_path='/videos/example.mp4')
    print(f"✓ 上传完成")
    
    # 查看最终状态
    upload = db.get_upload_by_id(upload_id)
    print(f"\n最终状态:")
    print(f"  - 状态: {upload['status']}")
    print(f"  - 远程路径: {upload['remote_path']}")
    print(f"  - 完成时间: {upload['completed_at']}")


def example_3_download_failed(upload_id):
    """示例3：下载失败导致上传失败"""
    print("\n" + "=" * 60)
    print("示例3：下载失败导致上传失败")
    print("=" * 60)
    
    # 标记上传失败，原因是下载失败
    db.mark_upload_failed(
        upload_id,
        failure_reason='download_failed',  # 关键：明确标记是下载失败
        error_message='Download was incomplete or failed',
        error_code='DL_001'
    )
    print(f"✓ 标记上传失败（原因：下载失败）")
    
    # 查看失败信息
    upload = db.get_upload_by_id(upload_id)
    print(f"\n失败信息:")
    print(f"  - 状态: {upload['status']}")
    print(f"  - 失败原因: {upload['failure_reason']}")
    print(f"  - 错误信息: {upload['error_message']}")
    print(f"  - 错误代码: {upload['error_code']}")


def example_4_code_error(upload_id):
    """示例4：代码错误导致上传失败"""
    print("\n" + "=" * 60)
    print("示例4：代码错误导致上传失败")
    print("=" * 60)
    
    # 标记上传失败，原因是代码错误
    db.mark_upload_failed(
        upload_id,
        failure_reason='code_error',  # 关键：明确标记是代码错误
        error_message='NoneType object has no attribute upload',
        error_code='CODE_001'
    )
    print(f"✓ 标记上传失败（原因：代码错误）")
    
    # 查看失败信息
    upload = db.get_upload_by_id(upload_id)
    print(f"\n失败信息:")
    print(f"  - 状态: {upload['status']}")
    print(f"  - 失败原因: {upload['failure_reason']}")
    print(f"  - 错误信息: {upload['error_message']}")


def example_5_retry_logic(upload_id):
    """示例5：重试逻辑"""
    print("\n" + "=" * 60)
    print("示例5：重试逻辑")
    print("=" * 60)
    
    # 获取当前上传信息
    upload = db.get_upload_by_id(upload_id)
    max_retries = upload['max_retries']
    
    # 增加重试次数
    new_retry_count = db.increment_upload_retry(upload_id)
    print(f"✓ 重试次数: {new_retry_count} / {max_retries}")
    
    # 检查是否超过最大重试次数
    if new_retry_count >= max_retries:
        print(f"✗ 已达到最大重试次数，放弃上传")
        db.mark_upload_failed(
            upload_id,
            failure_reason='timeout',
            error_message=f'Max retries ({max_retries}) exceeded'
        )
    else:
        print(f"✓ 可以继续重试")


def example_6_query_uploads():
    """示例6：查询上传记录"""
    print("\n" + "=" * 60)
    print("示例6：查询上传记录")
    print("=" * 60)
    
    # 查询最近的上传记录
    recent_uploads = db.fetch_recent_uploads(limit=10)
    print(f"✓ 最近 {len(recent_uploads)} 条上传记录:")
    for upload in recent_uploads[:3]:  # 只显示前3条
        print(f"  - ID: {upload['id']}, 状态: {upload['status']}, "
              f"目标: {upload['upload_target']}, 文件: {upload.get('file_name', 'N/A')}")
    
    # 查询失败的上传
    failed_uploads = db.fetch_recent_uploads(limit=100, status='failed')
    print(f"\n✓ 失败的上传记录: {len(failed_uploads)} 条")
    
    # 查询待上传的记录
    pending_uploads = db.get_pending_uploads(upload_target='onedrive')
    print(f"✓ 待上传到 OneDrive 的记录: {len(pending_uploads)} 条")


def example_7_statistics():
    """示例7：统计分析"""
    print("\n" + "=" * 60)
    print("示例7：统计分析")
    print("=" * 60)
    
    # 获取完整统计信息
    stats = db.get_upload_statistics()
    print(f"总体统计:")
    print(f"  - 总数: {stats.get('total', 0)}")
    print(f"  - 已完成: {stats.get('completed', 0)}")
    print(f"  - 失败: {stats.get('failed', 0)}")
    print(f"  - 上传中: {stats.get('uploading', 0)}")
    print(f"  - 待上传: {stats.get('pending', 0)}")
    
    # 按目标统计
    print(f"\n按上传目标统计:")
    for target, count in stats.get('by_target', {}).items():
        print(f"  - {target}: {count}")
    
    # 失败原因统计（关键：区分下载失败和代码错误）
    print(f"\n失败原因统计:")
    failure_stats = stats.get('by_failure_reason', {})
    if failure_stats:
        for reason, count in failure_stats.items():
            print(f"  - {reason}: {count}")
        
        # 计算下载失败占比
        download_failed = failure_stats.get('download_failed', 0)
        code_error = failure_stats.get('code_error', 0)
        total_failed = sum(failure_stats.values())
        
        if total_failed > 0:
            print(f"\n失败原因分析:")
            print(f"  - 下载失败: {download_failed} ({download_failed/total_failed*100:.1f}%)")
            print(f"  - 代码错误: {code_error} ({code_error/total_failed*100:.1f}%)")
            print(f"  - 其他原因: {total_failed - download_failed - code_error} "
                  f"({(total_failed - download_failed - code_error)/total_failed*100:.1f}%)")
    else:
        print(f"  暂无失败记录")


def example_8_migrate_data():
    """示例8：迁移现有数据"""
    print("\n" + "=" * 60)
    print("示例8：迁移现有数据")
    print("=" * 60)
    
    # 从 downloads 表迁移上传数据到 uploads 表
    migrated_count = db.migrate_upload_data()
    print(f"✓ 已迁移 {migrated_count} 条上传记录")


def main():
    """主函数：运行所有示例"""
    print("\n" + "=" * 60)
    print("上传追踪表使用示例")
    print("=" * 60)
    
    # 初始化数据库
    print("\n初始化数据库...")
    db.init_db()
    print("✓ 数据库初始化完成")
    
    # 运行示例（注释掉实际执行，仅作为参考）
    # upload_id = example_1_create_upload()
    # example_2_upload_success_flow(upload_id)
    # example_3_download_failed(upload_id)
    # example_4_code_error(upload_id)
    # example_5_retry_logic(upload_id)
    # example_6_query_uploads()
    # example_7_statistics()
    # example_8_migrate_data()
    
    print("\n" + "=" * 60)
    print("示例代码说明:")
    print("=" * 60)
    print("1. 创建上传任务: create_upload()")
    print("2. 更新上传状态: mark_upload_started(), update_upload_status()")
    print("3. 标记完成/失败: mark_upload_completed(), mark_upload_failed()")
    print("4. 查询记录: get_upload_by_id(), fetch_recent_uploads()")
    print("5. 统计分析: get_upload_statistics(), count_uploads_by_failure_reason()")
    print("\n关键功能：通过 failure_reason 字段区分下载失败和代码错误")
    print("  - download_failed: 下载阶段失败")
    print("  - code_error: 代码逻辑错误")
    print("  - network_error: 网络错误")
    print("  - 其他原因...")


if __name__ == '__main__':
    main()
