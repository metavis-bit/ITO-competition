import json
import html

def render_process_animation(data: dict) -> str:
    title = html.escape(data.get("title", "系统进程全景图谱动态演绎"))
    steps_json = json.dumps(data.get("steps",), ensure_ascii=False)
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;800;900&display=swap" rel="stylesheet">
    
    <script>
        tailwind.config = {{ theme: {{ extend: {{ fontFamily: {{ sans: ['Nunito', 'sans-serif'] }} }} }} }}
    </script>
    <style>
        /* 营造宇宙深空科技感背景 */
        body {{ background: radial-gradient(circle at top right, #1e293b, #0f172a); color: #f8fafc; overflow: hidden; }}
        
       .glass-stage {{
            background: rgba(15, 23, 42, 0.6);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 40px;
            box-shadow: 0 30px 60px -15px rgba(0, 0, 0, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.1);
        }}
        
        /* 核心图元无限悬浮动画 */
       .icon-float {{ animation: float 4s ease-in-out infinite; }}
        @keyframes float {{
            0% {{ transform: translateY(0px) rotate(0deg); }}
            50% {{ transform: translateY(-20px) rotate(3deg); }}
            100% {{ transform: translateY(0px) rotate(0deg); }}
        }}
        
       .nav-btn {{ transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); }}
       .nav-btn:active:not(:disabled) {{ transform: scale(0.92); }}
    </style>
</head>
<body class="flex flex-col items-center justify-center min-h-screen p-4 md:p-8">

    <div class="w-full max-w-5xl glass-stage p-10 md:p-16 relative flex flex-col items-center">
        <div id="progress-dots" class="flex space-x-4 mb-10"></div>
        
        <h1 class="text-3xl font-black text-slate-400 tracking-[0.2em] uppercase mb-16 opacity-80">{title}</h1>
        
        <div class="flex flex-col items-center text-center min-h-[350px] w-full relative" id="stage">
            <div id="anim-icon" class="text-8xl md:text-[10rem] mb-10 drop-shadow-[0_0_40px_rgba(56,189,248,0.6)] icon-float"></div>
            <h2 id="anim-title" class="text-4xl md:text-5xl font-black text-white mb-6 tracking-tight"></h2>
            <p id="anim-desc" class="text-2xl text-slate-300 leading-relaxed max-w-3xl font-medium"></p>
        </div>

        <div class="flex justify-between items-center w-full mt-16 px-4 md:px-10">
            <button id="btn-prev" class="nav-btn px-8 py-4 rounded-full font-bold bg-slate-800 text-slate-300 border-2 border-slate-700 hover:bg-slate-700 disabled:opacity-20 text-lg" onclick="nav(-1)">
                <i class="fa-solid fa-chevron-left mr-2"></i> 时序回溯
            </button>
            <div class="text-slate-500 font-extrabold text-2xl py-3 tracking-widest"><span id="step-counter" class="text-sky-400"></span> <span class="opacity-50">/</span> <span id="step-total"></span></div>
            <button id="btn-next" class="nav-btn px-8 py-4 rounded-full font-black bg-sky-500 text-white hover:bg-sky-400 shadow-[0_0_30px_rgba(14,165,233,0.5)] text-lg border-2 border-sky-400" onclick="nav(1)">
                推进演绎 <i class="fa-solid fa-chevron-right ml-2"></i>
            </button>
        </div>
    </div>

    <script>
        const steps = {steps_json};
        let cur = 0;
        let isAnimating = false; // 节流锁，防止连击阻断动画

        document.getElementById('step-total').innerText = steps.length;
        
        // 动态构建指引灯阵
        const dotsContainer = document.getElementById('progress-dots');
        steps.forEach((_, i) => {{
            const dot = document.createElement('div');
            dot.id = `dot-${{i}}`;
            dot.className = "w-4 h-4 rounded-full bg-slate-700 transition-all duration-500";
            dotsContainer.appendChild(dot);
        }});

        function playStepAnimation(direction) {{
            isAnimating = true;
            const tl = gsap.timeline({{ onComplete: () => {{ isAnimating = false; }} }});
            
            // 旧内容离场序列 (Timeline sequenced exit) 
            tl.to(["#anim-icon", "#anim-title", "#anim-desc"], {{
                y: direction > 0? -40 : 40, 
                opacity: 0, 
                duration: 0.3, 
                stagger: 0.08,
                ease: "power2.in"
            }});
            
            // DOM 数据静默置换 (JS Callback inside Timeline)
            tl.call(() => {{
                document.getElementById('anim-icon').innerText = steps[cur].icon;
                document.getElementById('anim-title').innerText = steps[cur].title;
                document.getElementById('anim-desc').innerText = steps[cur].description;
            }});
            
            // 新内容进场序列 (Timeline sequenced entrance)
            tl.fromTo(["#anim-icon", "#anim-title", "#anim-desc"], 
                {{ y: direction > 0? 40 : -40, opacity: 0 }},
                {{ y: 0, opacity: 1, duration: 0.6, stagger: 0.1, ease: "back.out(1.2)" }}
            );
        }}

        function updateUI(direction) {{
            document.getElementById('step-counter').innerText = cur + 1;
            
            // 同步指引灯阵状态颜色
            steps.forEach((_, i) => {{
                const dot = document.getElementById(`dot-${{i}}`);
                if(i < cur) dot.className = "w-4 h-4 rounded-full bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.9)]";
                else if(i === cur) dot.className = "w-6 h-4 rounded-full bg-sky-400 shadow-[0_0_20px_rgba(56,189,248,0.9)]"; // 聚焦时拉长
                else dot.className = "w-4 h-4 rounded-full bg-slate-700";
            }});
            
            // 处理边界态按钮
            document.getElementById('btn-prev').disabled = cur === 0;
            const nextBtn = document.getElementById('btn-next');
            if(cur === steps.length - 1) {{
                nextBtn.innerHTML = "重新演算 <i class='fa-solid fa-rotate-right ml-2'></i>";
                nextBtn.classList.replace('bg-sky-500', 'bg-emerald-500');
                nextBtn.classList.replace('border-sky-400', 'border-emerald-400');
                nextBtn.classList.replace('hover:bg-sky-400', 'hover:bg-emerald-400');
                nextBtn.style.boxShadow = '0 0 30px rgba(16,185,129,0.5)';
            }} else {{
                nextBtn.innerHTML = "推进演绎 <i class='fa-solid fa-chevron-right ml-2'></i>";
                nextBtn.classList.replace('bg-emerald-500', 'bg-sky-500');
                nextBtn.classList.replace('border-emerald-400', 'border-sky-400');
                nextBtn.classList.replace('hover:bg-emerald-400', 'hover:bg-sky-400');
                nextBtn.style.boxShadow = '0 0 30px rgba(14,165,233,0.5)';
            }}
            
            playStepAnimation(direction);
        }}

        window.nav = function(dir) {{
            if (isAnimating) return; // 防止狂按导致的动画队列重叠
            if (cur + dir >= steps.length) {{
                cur = 0; // 重置游标
                updateUI(1);
                return;
            }}
            cur += dir;
            updateUI(dir);
        }}

        // 系统冷启动首帧加载
        updateUI(1);
    </script>
</body>
</html>
"""
    return html_content
