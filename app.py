import streamlit as st
import numpy as np
import pandas as pd
import ezdxf
from ezdxf.enums import TextEntityAlignment
from scipy.interpolate import griddata
from scipy.spatial import ConvexHull  # Thuật toán tìm chu vi đường bao
from shapely.geometry import Polygon, MultiPolygon # Thư viện tính toán cắt tỉa hình học
import io

st.set_page_config(page_title="Earthwork Grid Calculator", layout="wide")
st.title("🧮 Web App Tính Khối Lượng Đào Đắp Cắt Tỉa Lưới Theo Ranh Giới")

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
if "boundary_poly_coords" not in st.session_state:
    st.session_state.boundary_poly_coords = None

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

st.sidebar.subheader("Ranh giới tính toán")
boundary_mode = st.sidebar.selectbox("Loại dữ liệu ranh giới", ["Sử dụng chu vi bề mặt 2 làm ranh giới"])

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
                points.append([float(parts), float(parts), float(parts)])
        except:
            continue
    return np.array(points) if len(points) > 0 else None

# --- XỬ LÝ SỰ KIỆN TÍNH TOÁN ---
if st.sidebar.button("👉 Tiến hành tính toán khối lượng"):
    pts1 = load_real_points(surface_1)
    pts2 = load_real_points(surface_2)
    
    st.session_state.pts1_real = pts1
    st.session_state.pts2_real = pts2
    
    valid = True
    if surface_1["type"] == "txt" and pts1 is None:
        st.sidebar.error("❌ Kiểm tra lại file TXT Bề mặt 1.")
        valid = False
    if surface_2["type"] == "txt" and pts2 is None:
        st.sidebar.error("❌ Kiểm tra lại file TXT Bề mặt 2.")
        valid = False
    if surface_2["type"] == "const" and boundary_mode == "Sử dụng chu vi bề mặt 2 làm ranh giới":
        st.sidebar.error("❌ Không thể lấy chu vi nếu Bề mặt 2 là mặt phẳng hằng số. Vui lòng up file TXT cho Bề mặt 2.")
        valid = False
        
    if valid:
        hull = ConvexHull(pts2[:, :2])
        boundary_vertices = pts2[hull.vertices, :2]
        boundary_polygon = Polygon(boundary_vertices)
        st.session_state.boundary_poly_coords = list(boundary_polygon.exterior.coords)
        
        x_min, y_min, x_max, y_max = boundary_polygon.bounds
        
        x_coords = np.arange(x_min, x_max + grid_size, grid_size)
        y_coords = np.arange(y_min, y_max + grid_size, grid_size)
        
        grid_rows_list = []
        cad_cells = []
        total_cut_vol = 0.0
        total_fill_vol = 0.0
        
        for r_idx in range(len(y_coords) - 1):
            row_cells_data = []
            y_start = y_coords[r_idx]
            y_end = y_coords[r_idx + 1]
            
            for c_idx in range(len(x_coords) - 1):
                x_start = x_coords[c_idx]
                x_end = x_coords[c_idx + 1]
                
                cell_poly = Polygon([
                    (x_start, y_start),
                    (x_end, y_start),
                    (x_end, y_end),
                    (x_start, y_end)
                ])
                
                if not cell_poly.intersects(boundary_polygon):
                    row_cells_data.append("Ngoài RG")
                    continue
                
                intersected_geo = cell_poly.intersection(boundary_polygon)
                actual_area = intersected_geo.area
                
                grid_lines_to_draw = []
                if isinstance(intersected_geo, Polygon):
                    grid_lines_to_draw.append(list(intersected_geo.exterior.coords))
                elif isinstance(intersected_geo, MultiPolygon):
                    for poly in intersected_geo.geoms:
                        grid_lines_to_draw.append(list(poly.exterior.coords))
                
                cx, cy = intersected_geo.centroid.x, intersected_geo.centroid.y
                corners_eval = np.array([[cx, cy]])
                
                def get_z_at_centroid(pts_data, surface_cfg):
                    if surface_cfg["type"] == "const":
                        return surface_cfg["value"]
                    else:
                        z_val = griddata(pts_data[:, :2], pts_data[:, 2], corners_eval, method='linear')
                        if np.isnan(z_val):
                            z_val = griddata(pts_data[:, :2], pts_data[:, 2], corners_eval, method='nearest')
                        return z_val
                
                z1_center = get_z_at_centroid(pts1, surface_1)
                z2_center = get_z_at_centroid(pts2, surface_2)
                
                dz = z2_center - z1_center
                volume = actual_area * dz
                
                if volume < 0:
                    cut_v = abs(volume)
                    fill_v = 0.0
                    cell_str = f"Đào: {cut_v:.1f} m³"
                else:
                    cut_v = 0.0
                    fill_v = volume
                    cell_str = f"Đắp: {fill_v:.1f} m³"
                    
                total_cut_vol += cut_v
                total_fill_vol += fill_v
                row_cells_data.append(f"{cell_str} ({actual_area:.1f}㎡)")
                
                cad_cells.append({
                    'lines': grid_lines_to_draw,
                    'cx': cx, 'cy': cy,
                    'volume': -cut_v if cut_v > 0 else fill_v
                })
                
            grid_rows_list.append(row_cells_data)
            
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
    st.success("🎉 Đã hoàn thành tính toán khối lượng đào đắp cắt tỉa theo ranh giới chu vi Bề mặt 2!")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Tổng khối lượng ĐÀO 🟥", f"{st.session_state.total_cut:,.2f} m³")
    col2.metric("Tổng khối lượng ĐẮP 🟩", f"{st.session_state.total_fill:,.2f} m³")
    net_diff = st.session_state.total_fill - st.session_state.total_cut
    col3.metric("Khối lượng cân bằng chênh lệch", f"{net_diff:,.2f} m³", delta_color="inverse")

    st.subheader("📊 Bảng phân bố lưới ô vuông đã cắt tỉa (Diện tích giao ㎡ thực tế)")
    st.dataframe(st.session_state.df_result, use_container_width=True)
    
    st.subheader("💾 Tải về file thành phẩm tích hợp số liệu thực")
    dwn_col1, dwn_col2 = st.columns(2)
    
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        st.session_state.df_result.to_excel(writer, index=False, sheet_name="Khoi_Luong_Cat_Tia")
    excel_data = output_excel.getvalue()
    
    with dwn_col1:
        st.download_button(
            label="📥 Tải xuống Bảng tính Excel thực tế (.xlsx)",
            data=excel_data,
            file_name="khoi_luong_cat_tia_ranh_gioi.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
    # --- THUẬT TOÁN XUẤT CAD DXF KẾT HỢP DỮ LIỆU THỰC ĐỊA CHUẨN XÁC ---
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    # Thiết lập Layer hệ thống
    doc.layers.new(name='SURFACE_1', dxfattribs={'color': 1})    # Đỏ (Hiện trạng)
    doc.layers.new(name='SURFACE_2', dxfattribs={'color': 3})    # Xanh lá (Các điểm và cao độ Thiết kế)
    doc.layers.new(name='GRID_LINES', dxfattribs={'color': 7})   # Trắng/Đen (Đường lưới ô vuông bị cắt tỉa)
    doc.layers.new(name='EARTHWORK_CUT', dxfattribs={'color': 1}) # Đỏ (Khối lượng Đào)
    doc.layers.new(name='EARTHWORK_FILL', dxfattribs={'color': 3})# Xanh lá (Khối lượng Đắp)

    # Vẽ các điểm của Bề mặt 1 lên Layer SURFACE_1
    if st.session_state.pts1_real is not None:
        for pt in st.session_state.pts1_real:
            x, y, z = float(pt), float(pt), float(pt)
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_1'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_1', 'height': 0.3}).set_placement((x + 0.2, y, z))

    # Vẽ các điểm của Bề mặt 2 lên Layer SURFACE_2
    if st.session_state.pts2_real is not None:
        for pt in st.session_state.pts2_real:
            x, y, z = float(pt), float(pt), float(pt)
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_2'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_2', 'height': 0.3}).set_placement((x + 0.2, y, z))

    # ĐÃ CẬP NHẬT: Vẽ đường ranh giới kín màu VÀNG ('color': 2) nhưng vẫn thuộc Layer SURFACE_2 để dễ nhận biết
    if st.session_state.boundary_poly_coords is not None:
        msp.add_lwpolyline(
            st.session_state.boundary_poly_coords, 
            dxfattribs={
                'layer': 'SURFACE_2', 
                'color': 2,            # Mã màu AutoCAD số 2 = Vàng (Yellow)
                'const_width': 0.15     # Độ dày nét vẽ tăng nhẹ để làm nổi bật đường bao
            }
        )

    # Vẽ hệ lưới ô vuông đã được CẮT TỈA theo ranh giới (Layer GRID_LINES)
    for cell in st.session_state.cad_grid_data:
        for poly_line in cell['lines']:
            for i in range(len(poly_line) - 1):
                p1 = poly_line[i]
                p2 = poly_line[i+1]
                msp.add_line(p1, p2, dxfattribs={'layer': 'GRID_LINES'})
                
        cx, cy = cell['cx'], cell['cy']
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
            label="📥 Tải xuống Bản vẽ CAD Lưới Đã Cắt Tỉa (.dxf)",
            data=dxf_data,
            file_name="khoi_luong_cat_tia_chinh_xac.dxf",
            mime="application/dxf",
            use_container_width=True
        )
else:
    st.info("💡 Hướng dẫn: Tải lên file TXT ở Sidebar trái, hệ thống sẽ tự động bóc tách đường chu vi của Bề mặt 2 để làm ranh giới màu vàng.")
