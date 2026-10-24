tailwind.config = { theme: { extend: {
  colors: {
    background:"#f7fbf0", "on-surface":"#191d17", "on-surface-variant":"#40493d",
    "surface-container-lowest":"#ffffff", "surface-container-low":"#f2f5eb", "surface-container":"#ecefe5", "surface-container-high":"#e6e9e0",
    outline:"#707a6c", "outline-variant":"#bfcaba",
    primary:"#0d631b", "primary-container":"#2e7d32", "on-primary":"#ffffff",
    secondary:"#376a10", "secondary-container":"#b6f48a", "on-secondary-container":"#3d7116",
    tertiary:"#6b4f45", "tertiary-container":"#85675c", "tertiary-fixed":"#ffdbce",
    error:"#ba1a1a", "error-container":"#ffdad6"
  },
  borderRadius: { DEFAULT:"0.25rem", lg:"0.5rem", xl:"0.75rem", full:"9999px" },
  fontFamily: { sans:["Plus Jakarta Sans","system-ui","sans-serif"] },
  fontSize: {
    "label-sm":["11px",{lineHeight:"14px",letterSpacing:"0.02em",fontWeight:"500"}],
    "label-md":["12px",{lineHeight:"16px",letterSpacing:"0.02em",fontWeight:"600"}],
    "label-lg":["14px",{lineHeight:"20px",letterSpacing:"0.01em",fontWeight:"600"}],
    "body-sm":["12px",{lineHeight:"18px"}], "body-md":["14px",{lineHeight:"20px"}], "body-lg":["16px",{lineHeight:"24px"}],
    "headline-sm":["18px",{lineHeight:"26px",fontWeight:"600"}], "headline-md":["20px",{lineHeight:"28px",fontWeight:"600"}],
    "headline-lg":["30px",{lineHeight:"38px",letterSpacing:"-0.015em",fontWeight:"600"}]
  }
}}};
