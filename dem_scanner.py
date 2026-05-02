import os
import numpy as np
import requests
try:
    import rasterio
    from rasterio.plot import show
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
except ImportError:
    print("🚨 请先安装依赖: pip install rasterio matplotlib numpy requests")
    exit()

# ==========================================
# 模块 1：本地 TIF 高程图“X光”扫描诊断
# ==========================================
def scan_local_dem(tif_path):
    print(f"\n🔍 [GIS 诊断室] 正在对高程图进行 X 光扫描: {tif_path}")
    if not os.path.exists(tif_path):
        print(f"❌ 找不到文件: {tif_path}")
        return

    with rasterio.open(tif_path) as src:
        dem_data = src.read(1).astype(np.float32)
        bounds = src.bounds
        nodata_val = src.nodata

        print("\n📊 [雷达元数据]")
        print(f"  - 经纬度边界: 左下({bounds.left:.4f}, {bounds.bottom:.4f}) -> 右上({bounds.right:.4f}, {bounds.top:.4f})")
        print(f"  - 矩阵分辨率: {src.width} x {src.height} 像素")
        print(f"  - 官方空值标记 (NODATA): {nodata_val}")

        # 统计物理黑洞
        total_pixels = src.width * src.height
        
        # 将官方空值、负数异常值、绝对 0 值全部视为“空洞”
        if nodata_val is not None:
            void_mask = (dem_data == nodata_val) | (dem_data <= 0)
        else:
            void_mask = (dem_data <= 0)

        void_pixels = np.sum(void_mask)
        valid_pixels = total_pixels - void_pixels
        health_rate = (valid_pixels / total_pixels) * 100

        print("\n🩺 [完整度体检报告]")
        print(f"  - 总采样点: {total_pixels:,} 个")
        print(f"  - 有效地形: {valid_pixels:,} 个")
        print(f"  - 雷达空洞: {void_pixels:,} 个 (包含 0 米或无法探测的深谷)")
        
        if health_rate < 95.0:
            print(f"  - ⚠️ 战区完整度: {health_rate:.2f}% (警告：存在严重的情报断层！)")
        else:
            print(f"  - ✅ 战区完整度: {health_rate:.2f}% (健康，可用于精确制导与行军)")

        # 渲染 X 光诊断图
        print("\n🎨 正在生成战区病灶可视化图像...")
        
        # 创建一个掩码数组用于绘图，将空洞设为 NaN
        plot_data = np.where(void_mask, np.nan, dem_data)
        
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.set_title(f"DEM X-Ray Scan (Health: {health_rate:.2f}%) \nRed areas are Data Voids (0m or NoData)")
        
        # 绘制正常地形（使用地形色带）
        im = ax.imshow(plot_data, cmap='terrain', extent=[bounds.left, bounds.right, bounds.bottom, bounds.top])
        
        # 用鲜红色绘制空洞区域！
        cmap_red = ListedColormap(['red'])
        ax.imshow(void_mask, cmap=cmap_red, alpha=np.where(void_mask, 1.0, 0.0), extent=[bounds.left, bounds.right, bounds.bottom, bounds.top])
        
        plt.colorbar(im, ax=ax, label='Elevation (meters)')
        plt.xlabel('Longitude')
        plt.ylabel('Latitude')
        plt.show()

# ==========================================
# 模块 2：军工级无缝高程图下载 (OpenTopography)
# ==========================================
def download_void_filled_dem(min_lon, min_lat, max_lon, max_lat, output_file, api_key="demo"):
    """
    使用 OpenTopography API 下载 SRTM GL3 (90m) 或 GL1 (30m)。
    由于 SRTM GL 系列是经过算法填补的 (Void-Filled)，不会出现 0 米黑洞。
    """
    print(f"\n🛰️ [卫星上行链路] 正在请求全新的无缝高程扫描阵列...")
    
    # SRTMGL1 是 30m 精度, SRTMGL3 是 90m 精度。如果没有 API 密钥，可能会受到限制。
    dataset = "SRTMGL3" # 测试时建议先用 GL3 确保能下下来
    
    url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": dataset,
        "south": min_lat,
        "north": max_lat,
        "west": min_lon,
        "east": max_lon,
        "outputFormat": "GTiff",
        "API_Key": api_key
    }

    try:
        response = requests.get(url, params=params, stream=True)
        if response.status_code == 200:
            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✅ [下载完成] 完美的无缝高程图已保存至: {output_file}")
            # 下载完顺便给它做个体检
            scan_local_dem(output_file)
        else:
            print(f"❌ [下载失败] HTTP 状态码: {response.status_code}")
            print("如果提示需要 API Key，请前往 https://opentopography.org/ 免费注册一个并填入代码中。")
    except Exception as e:
        print(f"❌ [网络异常] {e}")


if __name__ == "__main__":
    print("="*50)
    print("CDC 战区高程测绘与诊断系统 v1.0")
    print("="*50)
    
    # 👇 请将这里的路径修改为你实际高程图的路径
    MY_TIF_PATH = "dlc/afghan/maps/afghan_core_30m.tif"
    
    # 1. 扫描你现有的地图
    scan_local_dem(MY_TIF_PATH)
    
    # 2. 如果你想下载一张新的（例如阿富汗中东部坐标），取消下面这行的注释
    # 注意：下载大范围的 30m 高程图需要你去 opentopography.org 免费注册一个 API_KEY
    # download_void_filled_dem(min_lon=66.0, min_lat=32.0, max_lon=71.0, max_lat=36.0, output_file="dlc/afghan_1986/maps/afghan_new_void_filled.tif", api_key="你的API_KEY写在这里")