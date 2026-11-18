# ซ่อน–แสดงเมนูซ้าย

- ปุ่มไอคอนด้านซ้ายของ TopBar ใช้ซ่อน/แสดงเมนูได้เสมอ แม้เมนูถูกซ่อน
- Desktop ซ่อนเมนูทั้งแผง จึงไม่เหลือพื้นที่กว้าง 212px ไว้ข้างกราฟ
- main และ header ใช้ความกว้างที่เหลือทั้งหมด กราฟใช้ ResizeObserver เดิม
  เพื่อปรับขนาดตามพื้นที่ใหม่ โดยไม่รีเซ็ตซูมเมื่อ Auto scroll ปิด
- จอเล็กใช้ drawer ทับหน้าจอ ไม่บีบกราฟ; เปิดแล้ว focus ปุ่มปิด,
  Tab อยู่ภายในแผง, Escape/คลิก backdrop/เลือกเมนูปิดแผงได้
- ปุ่มมี aria-expanded/aria-controls และชื่อเปลี่ยนตามสถานะ
- จำใน localStorage ของ browser: `no7.sidebar.expanded.v1` และ
  `no7.sidebar.mobile-open.v1` แยก Desktop/Mobile; default เปิด Desktop/ปิด Mobile
- เปิดครั้งถัดไปใน browser/profile เดิมจะคืนค่าที่บันทึก; ถ้าปิด storage
  ปุ่มยังทำงานใน session ได้ แต่จำข้ามครั้งไม่ได้
- คงเมนูตามสิทธิ์ platform super admin เดิม ไม่เปลี่ยนสิทธิ์หรือระบบบัญชี

ตรวจด้วย frontend smoke: อ่าน preference ที่ปิดไว้, toggle บันทึก true/false,
mobile state แยกจาก desktop, storage failure, restore button accessible,
mobile dialog และ event bindings; production build ผ่าน.
ยังไม่ตรวจ drag/resize และ mobile focus ด้วย browser จริงหลัง deploy.

พอร์ต UI พัฒนา 18000, VM bundle/API ผ่าน SSH 18080 → VM loopback 8000.
Rollback code/bundle ไป bb5452c ได้; ไม่ต้องเปลี่ยนฐานข้อมูลบัญชี.
