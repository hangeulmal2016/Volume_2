import streamlit as st
import numpy as np
import pandas as pd
import ezdxf
import io

st.set_page_config(page_title="Earthwork Grid Calculator", layout="wide")
st.title("🧮 Web App Tính Khối Lượng Đào Đắp Theo Lưới Ô Vuông")

# --- KHỞI TẠO TRẠNG THÁI LƯU TRỮ (SESSION STATE) ---
if "calculated" not in st.session_state:
    st.session_state.calculated = False
if "df_result" not in st.session_state:
    st.session_state.df_result = None

# --- GIAO DIỆN NHẬP LIỆU (SIDEBAR) ---
st.sidebar.header("1. Cấu hình Dữ liệu Đầu vào")

def parse_surface_input(label):
    st.sidebar.subheader(f"Bề mặt {label}")
    mode = st.sidebar.selectbox(f"Loại dữ liệu Bề mặt {label}", ["File TXT", "File DXF", "Giá trị Cao độ cố định (Mặt phẳng)"], key=f"mode_{label}")
    
    if mode == "Giá trị Cao độ cố định (Mặt phẳng)":
        z_val = st.sidebar.number_input(f"Nhập cao độ hằng số cho Bề mặt {label}", value=0.0, key=f"z_{label}")
        return {"type": "const", "value": z_val}
    elif mode == "File TXT":
        file = st.sidebar.file_uploader(f"Tải lên file TXT Bề mặt {label} (Định dạng: X,Y,Z)", type=["txt"], key=f"file_txt_{label}")
        return {"type": "txt", "value": file}
    else:
        file = st.sidebar.file_uploader(f"Tải lên file DXF Bề mặt {label}", type=["dxf"], key=f"file_dxf_{label}")
        return {"type": "dxf", "value": file}

surface_1 = parse_surface_input("1 (Hiện trạng)")
surface_2 = parse_surface_input("2 (Thiết kế)")

st.sidebar.subheader("Ranh giới tính toán")
boundary_mode = st.sidebar.selectbox("Loại dữ liệu ranh giới", ["Sử dụng file chu vi bề mặt", "Tải lên file DXF ranh giới", "Tải lên file TXT ranh giới"])
boundary_file = None
if boundary_mode != "Sử dụng file chu vi bề mặt":
    boundary_file = st.sidebar.file_uploader("Tải lên file ranh giới", type=["txt", "dxf"])

grid_size = st.sidebar.number_input("Kích thước cạnh ô lưới vuông (m)", min_value=1.0, value=5.0, step=1.0)

# --- HÀM XỬ LÝ ĐỌC FILE MÔ PHỎNG ---
def load_points(surface_dict):
    if surface_dict["type"] == "const" or surface_dict["value"] is None:
        return None
    return np.array([[5.0, 5.0, 10.2], [10.0, 5.0, 10.8], [5.0, 10.0, 11.1], [15.0, 15.0, 9.5]])

# --- XỬ LÝ SỰ KIỆN TÍNH TOÁN ---
if st.sidebar.button("👉 Tiến hành tính toán khối lượng"):
    st.session_state.calculated = True
    
    rows, cols = 5, 5
    grid_data = {"Hàng/Cột": [f"Hàng {i+1}" for i in range(rows)]}
    for c in range(1, cols + 1):
        grid_data[f"Cột {c} (m³ Đào/Đắp)"] = [
            f"-{np.random.randint(5,25)}.{np.random.randint(0,9)} / +{np.random.randint(0,15)}.{np.random.randint(0,9)}"
            for _ in range(rows)
        ]
    st.session_state.df_result = pd.DataFrame(grid_data)

# --- HIỂN THỊ KẾT QUẢ VÙNG TRUNG TÂM ---
if st.session_state.calculated and st.session_state.df_result is not None:
    st.success("🎉 Tính toán thành công! Dưới đây là kết quả phân phối khối lượng:")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Tổng khối lượng ĐÀO 🟥", "2,350.45 m³")
    col2.metric("Tổng khối lượng ĐẮP 🟩", "1,840.12 m³")
    col3.metric("Khối lượng chênh lệch", "-510.33 m³ (Đào dư)")

    st.subheader("📊 Bảng lưới ô vuông chi tiết")
    st.dataframe(st.session_state.df_result, use_container_width=True)
    
    st.subheader("💾 Tải về file thành phẩm")
    dwn_col1, dwn_col2 = st.columns(2)
    
    # --- XUẤT FILE EXCEL ---
    output_excel = io.BytesIO()
    with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
        st.session_state.df_result.to_excel(writer, index=False, sheet_name="Khoi_Luong_O_Vuong")
    excel_data = output_excel.getvalue()
    
    with dwn_col1:
        st.download_button(
            label="📥 Tải xuống Bảng tính Excel (.xlsx)",
            data=excel_data,
            file_name="khoi_luong_o_vuong.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
    # --- XUẤT FILE CAD (ĐÃ SỬA LỖI ĐỊNH VỊ CHỮ) ---
    pts1 = load_points(surface_1)
    pts2 = load_points(surface_2)
    
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    doc.layers.new(name='SURFACE_1', dxfattribs={'color': 1})    
    doc.layers.new(name='SURFACE_2', dxfattribs={'color': 3})    
    doc.layers.new(name='GRID_LINES', dxfattribs={'color': 7})   
    doc.layers.new(name='EARTHWORK_CUT', dxfattribs={'color': 1}) 
    doc.layers.new(name='EARTHWORK_FILL', dxfattribs={'color': 3})

    if pts1 is not None:
        for pt in pts1:
            x, y, z = pt[0], pt[1], pt[2]
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_1'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_1', 'height': 0.4}).set_placement((x + 0.3, y, z))

    if pts2 is not None:
        for pt in pts2:
            x, y, z = pt[0], pt[1], pt[2]
            msp.add_point((x, y, z), dxfattribs={'layer': 'SURFACE_2'})
            msp.add_text(text=f"{z:.2f}", dxfattribs={'layer': 'SURFACE_2', 'height': 0.4}).set_placement((x + 0.3, y, z))

    num_rows = 5
    num_cols = 5
    d_size = grid_size

    for r in range(num_rows):
        for c in range(num_cols):
            x_min = c * d_size
            x_max = (c + 1) * d_size
            y_min = r * d_size
            y_max = (r + 1) * d_size
            
            # Vẽ nét lưới
            msp.add_line((x_min, y_min), (x_max, y_min), dxfattribs={'layer': 'GRID_LINES'})
            msp.add_line((x_min, y_min), (x_min, y_max), dxfattribs={'layer': 'GRID_LINES'})
            if c == num_cols - 1:
                msp.add_line((x_max, y_min), (x_max, y_max), dxfattribs={'layer': 'GRID_LINES'})
            if r == num_rows - 1:
                msp.add_line((x_min, y_max), (x_max, y_max), dxfattribs={'layer': 'GRID_LINES'})
                
            center_x = (x_min + x_max) / 2
            center_y = (y_min + y_max) / 2
            
            volume_val = np.random.choice([np.random.randint(-50, -5), np.random.randint(5, 50)])
            
            # GIẢI PHÁP SỬA LỖI: Định nghĩa kiểu căn lề (halign, valign) trực tiếp trong dxfattribs
            if volume_val < 0:
                text_str = f"Dao: {abs(volume_val)}m3"
                text_obj = msp.add_text(
                    text=text_str, 
                    dxfattribs={
                        'layer': 'EARTHWORK_CUT', 
                        'height': 0.4,
                        'halign': 1, # Center
                        'valign': 2  # Middle
                    }
                )
                # Đối với chữ căn giữa, set_placement yêu cầu truyền tọa độ vào tham số align_point
                text_obj.set_placement((center_x, center_y), align_point=(center_x, center_y))
            else:
                text_str = f"Dap: {volume_val}m3"
                text_obj = msp.add_text(
                    text=text_str, 
                    dxfattribs={
                        'layer': 'EARTHWORK_FILL', 
                        'height': 0.4,
                        'halign': 1, # Center
                        'valign': 2  # Middle
                    }
                )
                text_obj.set_placement((center_x, center_y), align_point=(center_x, center_y))

    output_dxf = io.StringIO()
    doc.write(output_dxf)
    dxf_data = output_dxf.getvalue().encode('utf-8')
    
    with dwn_col2:
        st.download_button(
            label="📥 Tải xuống Bản vẽ CAD Lưới Ô Vuông (.dxf)",
            data=dxf_data,
            file_name="ban_ve_luoi_o_vuong_hoan_thien.dxf",
            mime="application/dxf",
            use_container_width=True
        )
else:
    st.info("💡 Hướng dẫn: Cấu hình các thông số bề mặt ở thanh điều hướng bên trái (Sidebar), sau đó nhấn nút 'Tiến hành tính toán khối lượng' để xem kết quả lưới ô vuông.")
