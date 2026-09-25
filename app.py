import streamlit as st
import numpy as np
import pandas as pd
import ezdxf
from ezdxf.enums import TextEntityAlignment
from scipy.interpolate import griddata
import io

st.set_page_config(page_title="Earthwork Grid Calculator", layout="wide")
st.title("🧮 Web App Tính Khối Lượng Đào Đắp Lưới Ô Vuông Chuyên Nghiệp")

# --- KHỞI TẠO TRẠNG THÁI LƯU TRỮ (SESSION STATE) ---
if "calculated" not in st.session_state:
    st.session_state.calculated = False
if "df_result" not in st.session_state:
    st.session_state.df_result = None
if "total_cut" not in st.session_state:
    st.session_state.total_cut = 0.0
if "total_fill" not in st.session_state:
    st.session_state.total_fill = 0.0
if "cad_grid_data" not in st.session_state:
    st.session_state.cad_grid_data = []
if "pts1_real" not in st.session_state:
    st.session_state.pts1_real = None
if "pts2_real" not in st.session_state:
    st.session_state.pts2_real = None

# --- GIAO DIỆN NHẬP LIỆU (SIDEBAR) ---
st.sidebar.header("1. Cấu hình Dữ liệu Đầu vào")

def parse_surface_input(label):
    st.sidebar.subheader(f"Bề mặt {label}")
    mode = st.sidebar.selectbox(f"Loại dữ liệu Bề mặt {label}", ["File TXT", "Giá trị Cao độ cố định (Mặt phẳng)"], key=f"mode_{label}")
    
    if mode == "Giá trị Cao độ cố định (Mặt phẳng)":
        z_val = st.sidebar.number_input(f"Nhập cao độ hằng số cho Bề mặt {label}", value=0.0, key=f"z_{label}")
        return {"type": "const", "value": z_val}
    else:
        file = st.sidebar.file_uploader(f"Tải lên file TXT Bề mặt {label} (Định dạng: X Y Z)", type=["txt"], key=f"file_txt_{label}")
        return {"type": "txt", "value": file}

surface_1 = parse_surface_input("1 (Hiện trạng)")
surface_2 = parse_surface_input("2 (Thiết kế)")

grid_size = st.sidebar.number_input("Kích thước cạnh ô lưới vuông (m)", min_value=1.0, value=5.0, step=1.0)

# --- HÀM PARSER ĐỌC FILE TXT ---
def load_real_points(surface_dict):
    if surface_dict["type"] == "const" or surface_dict["value"] is None:
        return None
    points = []
    content = surface_dict["value"].read().decode("utf-8")
    surface_dict["value"].seek(0)
    
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            cleaned_line = line.replace(",", " ")
            parts = cleaned_line.split()
            if len(parts) >= 3:
                points.append([float(parts[0]), float(parts[1]), float(parts[2])])
        except:
            continue
    return np.array(points) if len(points) > 0 else None

# --- XỬ LÝ SỰ KIỆN TÍNH TOÁN VỚI THUẬT TOÁN NỘI SUY TUYẾN TÍNH (TIN-BASED) ---
if st.sidebar.button("👉 Tiến hành tính toán khối lượng"):
    pts1 = load_real_points(surface_1)
    pts2 = load_real_points(surface_2)
    
    st.session_state.pts1_real = pts1
    st.session_state.pts2_real = pts2
    
    # 1. Kiểm tra tính hợp lệ dữ liệu đầu vào
    valid = True
    if surface_1["type"] == "txt" and pts1 is None:
        st.sidebar.error("❌ Kiểm tra lại file TXT Bề mặt 1 (yêu cầu định dạng 3 cột: X Y Z).")
        valid = False
    if surface_2["type"] == "txt" and pts2 is None:
        st.sidebar.error("❌ Kiểm tra lại file TXT Bề mặt 2 (yêu cầu định dạng 3 cột: X Y Z).")
        valid = False
        
    if valid:
        # Xác định hộp giới hạn (Bounding Box) để phủ lưới ô vuông
        all_x, all_y = [], []
        if pts1 is not None:
            all_x.extend(pts1[:, 0])
            all_y.extend(pts1[:, 1])
        if pts2 is not None:
            all_x.extend(pts2[:, 0])
            all_y.extend(pts2[:, 1])
            
        # Nếu cả 2 đều là mặt phẳng hằng số, tạo một vùng lưới mặc định từ (0,0) đến (50,50)
        if len(all_x) == 0:
            x_min, x_max, y_min, y_max = 0.0, 50.0, 0.0, 50.0
        else:
            x_min, x_max = min(all_x), max(all_x)
            y_min, y_max = min(all_y), max(all_y)
            
        # Tạo ma trận tọa độ lưới ô vuông thực tế
        x_coords = np.arange(x_min, x_max + grid_size, grid_size)
        y_coords = np.arange(y_min, y_max + grid_size, grid_size)
        
        # Khởi tạo ma trận tích lũy để lưu trữ kết quả hiển thị bảng
        grid_rows_list = []
        cad_cells = []
        total_cut_vol = 0.0
        total_fill_vol = 0.0
        
        # Lặp qua từng ô lưới để tính toán khối lượng theo phương pháp lăng trụ
        for r_idx in range(len(y_coords) - 1):
            row_cells_data = []
            y_start = y_coords[r_idx]
            y_end = y_coords[r_idx + 1]
            
            for c_idx in range(len(x_coords) - 1):
                x_start = x_coords[c_idx]
                x_end = x_coords[c_idx + 1]
                
                # 4 đỉnh hình học góc ô lưới vuông
                corners = np.array([
                    [x_start, y_start],
                    [x_end, y_start],
                    [x_end, y_end],
                    [x_start, y_end]
                ])
                
                # Hàm nội suy cao độ cho từng đỉnh
                def get_z_values(pts_data, surface_cfg):
                    if surface_cfg["type"] == "const":
                        return np.full(4, surface_cfg["value"])
                    else:
                        # Thực hiện nội suy Linear dựa trên cấu trúc tam giác phẳng ẩn (TIN)
                        z_interp = griddata(pts_data[:, :2], pts_data[:, 2], corners, method='linear')
                        # Nếu ngoài biên tam giác bị lỗi NaN, chuyển sang dùng IDW gần nhất để tránh mất ô lưới biên
                        if np.any(np.isnan(z_interp)):
                            z_interp = griddata(pts_data[:, :2], pts_data[:, 2], corners, method='nearest')
                        return z_interp
                
                z1_corners = get_z_values(pts1, surface_1)
                z2_corners = get_z_values(pts2, surface_2)
                
                # Tính độ chênh cao trung bình tại 4 đỉnh
                dz = z2_corners - z1_corners
                avg_dz = np.mean(dz)
                
                # Tính diện tích ô lưới hình học thực tế
                cell_area = grid_size * grid_size
                volume = cell_area * avg_dz
                
                # Phân định Đào hay Đắp
                if volume < 0: # Cao độ thiết kế thấp hơn hiện trạng -> ĐÀO
                    cut_v = abs(volume)
                    fill_v = 0.0
                    cell_str = f"Đào: {cut_v:.1f} m³"
                else: # Cao độ thiết kế cao hơn hiện trạng -> ĐẮP
                    cut_v = 0.0
                    fill_v = volume
                    cell_str = f"Đắp: {fill_v:.1f} m³"
                    
                total_cut_vol += cut_v
                total_fill_vol += fill_v
                row_cells_data.append(cell_str)
                
                # Lưu trữ thông tin hình học phục vụ riêng cho Render CAD DXF
                cad_cells.append({
                    'x_min': x_start, 'x_max': x_end,
                    'y_min': y_start, 'y_max': y_end,
                    'volume': -cut_v if cut_v > 0 else fill_v
                })
                
            grid_rows_list.append(row_cells_data)
            
        # Chuyển đổi dữ liệu sang định dạng DataFrame dạng hàng và cột để hiển thị trực quan
        if len(grid_rows_list) > 0:
            max_cols = max(len(r) for r in grid_rows_list)
            df_cols = [f"Cột {c+1}" for c in range(max_cols)]
            df_index = [f"Hàng {r+1}" for r in range(len(grid_rows_list))]
            
            st.session_state.df_result = pd.DataFrame(grid_rows_list, columns=df_cols, index=df_index).reset_index().rename(columns={'index': 'Hàng/Cột'})
            st.session_state.total_cut = total_cut_vol
            st.session_state.total_fill = total_fill_vol
            st.session_state.cad_grid_data = cad_cells
            st.session_state.calculated = True
# --- HIỂN THỊ KẾT QUẢ VÙNG TRUNG TÂM (PERSISTENT RENDER) ---
if st.session_state.calculated and st.session_state.df_result is not None:
    st.success("🎉 Đã hoàn thành thuật toán tính toán khối lượng chính xác thực địa!")
    
    # 1. Thống kê tổng hợp (Metrics)
    col1, col2, col3 = st.columns(3)
    col1.metric("Tổng khối lượng ĐÀO 🟥", f"{st.session_state.total_cut:,.2f} m³")
    col2.metric("Tổng khối lượng ĐẮP 🟩", f"{st.session_state.total_fill:,.2f} m³")
    net_diff = st.session_state.total_fill - st.session_state.total_cut
    col3.metric("Khối lượng cân bằng chênh lệch", f"{net_diff:,.2f} m³", delta_color="inverse")

    # 2. Bảng hiển thị kết quả phân phối dạng hàng/cột
    st.subheader("📊 Bảng phân bố lưới ô vuông (Kết quả tính toán thực tế)")
    st.dataframe(st.session_state.df_result, use_container_width=True)
    
    # 3. Xuất file báo cáo
    st.subheader("💾 Tải về file thành phẩm tích hợp số liệu thực")
    dwn_col1, dwn_col2 = st.columns(2)
    
    # Xuất Excel từ RAM
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        st.session_state.df_result.to_excel(writer, index=False, sheet_name="Khoi_Luong_Thuc_Te")
    excel_data = output_excel.getvalue()
    
    with dwn_col1:
        st.download_button(
            label="📥 Tải xuống Bảng tính Excel thực tế (.xlsx)",
            data=excel_data,
            file_name="khoi_luong_chinh_xac.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
    # --- THUẬT TOÁN XUẤT CAD DXF KẾT HỢP DỮ LIỆU THỰC ĐỊA CHUẨN XÁC ---
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    # Thiết lập Layer hệ thống
    doc.layers.new(name='SURFACE_1', dxfattribs={'color': 1})    
    doc.layers.new(name='SURFACE_2', dxfattribs={'color': 3})    
    doc.layers.new(name='GRID_LINES', dxfattribs={'color': 7})   
    doc.layers.new(name='EARTHWORK_CUT', dxfattribs={'color': 1}) 
    doc.layers.new(name='EARTHWORK_FILL', dxfattribs={'color': 3})

    # Vẽ chính xác tọa độ thực các điểm Bề mặt 1 lên CAD
    if st.session_state.pts1_real is not None:
        for pt in st.session_state.pts1_real:
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_1'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_1', 'height': 0.3}).set_placement((x + 0.2, y, z))

    # Vẽ chính xác tọa độ thực các điểm Bề mặt 2 lên CAD
    if st.session_state.pts2_real is not None:
        for pt in st.session_state.pts2_real:
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_2'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_2', 'height': 0.3}).set_placement((x + 0.2, y, z))

    # Tái cấu trúc hình học lưới ô vuông thực địa và ghi số liệu vào tâm ô lưới
    unique_lines = set()
    for cell in st.session_state.cad_grid_data:
        x1, x2, y1, y2 = cell['x_min'], cell['x_max'], cell['y_min'], cell['y_max']
        
        # Gom các đoạn thẳng bao quanh ô lưới tránh trùng nét vẽ đè trong CAD
        lines_to_add = [
            ((x1, y1), (x2, y1)),
            ((x1, y1), (x1, y2)),
            ((x2, y1), (x2, y2)),
            ((x1, y2), (x2, y2))
        ]
        for l in lines_to_add:
            # Sắp xếp tọa độ để loại trùng lặp cặp điểm đầu cuối
            sorted_line = tuple(sorted(l))
            if sorted_line not in unique_lines:
                unique_lines.add(sorted_line)
                msp.add_line(l[0], l[1], dxfattribs={'layer': 'GRID_LINES'})
                
        # Tính toán tọa độ tâm chính xác
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        val = cell['volume']
        
        if val < 0:
            text_str = f"Dao: {abs(val):.1f}m3"
            t_obj = msp.add_text(text=text_str, dxfattribs={'layer': 'EARTHWORK_CUT', 'height': 0.3})
            t_obj.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
        else:
            text_str = f"Dap: {val:.1f}m3"
            t_obj = msp.add_text(text=text_str, dxfattribs={'layer': 'EARTHWORK_FILL', 'height': 0.3})
            t_obj.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)

    output_dxf = io.StringIO()
    doc.write(output_dxf)
    dxf_data = output_dxf.getvalue().encode('utf-8')
    
    with dwn_col2:
        st.download_button(
            label="📥 Tải xuống Bản vẽ CAD Lưới Ô Vuông (.dxf)",
            data=dxf_data,
            file_name="khoi_luong_luoi_o_vuong.dxf",
            mime="application/dxf",
            use_container_width=True
        )
else:
    st.info("💡 Hướng dẫn: Tải lên file TXT hoặc thiết lập Cao độ cố định ở Sidebar trái, sau đó bấm nút 'Tiến hành tính toán khối lượng'.")
