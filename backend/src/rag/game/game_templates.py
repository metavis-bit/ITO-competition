import json
import html

# ==========================================
# 1. 工业级通用游戏沙箱容器 (Universal Shell)
# ==========================================
# 内置 Tailwind CSS Play CDN、GSAP高帧率动效引擎、拖拽排序库与全栈微交互组件
_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    
    <script src="https://cdn.tailwindcss.com"></script>
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
    
    <script src="https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"></script>
    
    <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js"></script>
    
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
    
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    fontFamily: {{ sans: }},
                    colors: {{
                        edtech: {{ 50: '#f0f9ff', 100: '#e0f2fe', 500: '#0ea5e9', 600: '#0284c7' }},
                        duo: {{ bg: '#ffffff', primary: '#58cc02', primaryShadow: '#58a700' }}
                    }},
                    boxShadow: {{
                        'duo-soft': '0 4px 0 0 rgba(226, 232, 240, 1)',
                        'duo-primary': '0 5px 0 0 #58a700',
                        'duo-danger': '0 5px 0 0 #dc2626',
                        'duo-warning': '0 5px 0 0 #d97706',
                    }}
                }}
            }}
        }}
    </script>
    
    <style>
        /* 玻璃拟态与深度空间构造 */
        body {{ 
            background: linear-gradient(135deg, #e0eafc 0%, #cfdef3 100%); 
            min-height: 100vh; 
            overflow-x: hidden; 
        }}
       .glass-stage {{
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(20px);
            border: 2px solid rgba(255, 255, 255, 0.6);
            box-shadow: 0 20px 40px -10px rgba(0,0,0,0.08);
            border-radius: 32px;
        }}
        
        /* Duolingo 物理阻尼按钮全局抽象 */
       .btn-physical {{
            transition: all 0.1s cubic-bezier(0.4, 0, 0.2, 1);
            transform: translateY(0);
        }}
       .btn-physical:active:not(:disabled) {{
            transform: translateY(4px)!important;
            box-shadow: 0 0 0 0 transparent!important;
        }}
        
        /* 隐形美化滚动条 */
        ::-webkit-scrollbar {{ width: 8px; }}
        ::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 8px; }}
    </style>
</head>
<body class="flex flex-col items-center justify-center p-4 md:p-8 antialiased text-slate-800">
    <div class="w-full max-w-4xl glass-stage p-6 md:p-12 relative overflow-hidden">
        <h1 class="text-3xl md:text-4xl font-black text-center text-slate-800 mb-2 tracking-tight">{title}</h1>
"""

_FOOTER = """
    </div>
</body>
</html>
"""

# ==========================================
# 游戏 1: 沉浸式互动选择题 (Quiz)
# ==========================================
def render_quiz(data: dict) -> str:
    title = html.escape(data.get("title", "核心知识极速选择"))
    q_json = json.dumps(data.get("questions",), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <div class="flex justify-between items-center mb-8 bg-slate-50 p-4 rounded-2xl border-2 border-slate-100">
            <span class="text-slate-500 font-extrabold text-lg"><i class="fa-solid fa-layer-group text-edtech-500 mr-2"></i>进程 <span id="q-counter" class="text-edtech-600">1</span> / <span id="q-total"></span></span>
            <div class="flex-1 mx-6 h-5 bg-slate-200 rounded-full overflow-hidden shadow-inner">
                <div id="progress-bar" class="h-full bg-duo-primary transition-all duration-500 ease-out" style="width: 0%"></div>
            </div>
            <span class="text-slate-500 font-extrabold text-lg"><i class="fa-solid fa-bolt text-yellow-400 mr-2"></i>能量点: <span id="score" class="text-yellow-500">0</span></span>
        </div>

        <div id="quiz-container" class="min-h-[350px]"></div>

        <div class="mt-10 flex justify-center space-x-6">
            <button id="btn-prev" class="btn-physical hidden px-8 py-4 rounded-2xl font-bold text-slate-500 bg-white border-2 border-slate-200 shadow-duo-soft hover:bg-slate-50 text-lg" onclick="nav(-1)">
                <i class="fa-solid fa-arrow-left mr-2"></i>返回勘误
            </button>
            <button id="btn-next" class="btn-physical px-10 py-4 rounded-2xl font-black text-white bg-duo-primary border-none shadow-duo-primary hover:bg-[#61df02] text-lg tracking-wide" onclick="nav(1)">
                继续挑战 <i class="fa-solid fa-arrow-right ml-2"></i>
            </button>
        </div>

    <script>
        const questions = {q_json};
        let cur = 0;
        let score = 0;
        const answered = new Array(questions.length).fill(null);

        document.getElementById('q-total').innerText = questions.length;

        function renderQ() {{
            const q = questions[cur];
            const container = document.getElementById('quiz-container');
            
            let htmlStr = `<div class="gsap-quiz-entry">
                <h2 class="text-2xl md:text-3xl font-extrabold mb-8 text-slate-800 leading-normal text-center">${{q.stem}}</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">`;
            
            q.options.forEach((opt) => {{
                const letter = opt.charAt(0);
                const isSelected = answered[cur] === letter;
                const isCorrectAns = q.answer === letter;
                const showResult = answered[cur]!== null;
                
                // 默认中性状态
                let btnClass = "bg-white border-2 border-slate-200 shadow-duo-soft text-slate-600 hover:border-edtech-400 hover:bg-edtech-50";
                let icon = `<span class="inline-flex w-10 h-10 items-center justify-center rounded-xl bg-slate-100 text-lg mr-4 font-black border-2 border-slate-200">${{letter}}</span>`;

                // 交互后结果态染色
                if (showResult) {{
                    if (isCorrectAns) {{
                        btnClass = "bg-[#ddf4ff] border-2 border-[#1cb0f6] shadow-[0_4px_0_0_#1899d6] text-[#1899d6]";
                        icon = `<span class="inline-flex w-10 h-10 items-center justify-center rounded-xl bg-[#1cb0f6] text-white text-lg mr-4 font-black"><i class="fa-solid fa-check"></i></span>`;
                    }} else if (isSelected &&!isCorrectAns) {{
                        btnClass = "bg-[#ffdfe0] border-2 border-[#ff4b4b] shadow-[0_4px_0_0_#ea2b2b] text-[#ea2b2b] opacity-80";
                        icon = `<span class="inline-flex w-10 h-10 items-center justify-center rounded-xl bg-[#ff4b4b] text-white text-lg mr-4 font-black"><i class="fa-solid fa-xmark"></i></span>`;
                    }} else {{
                        btnClass += " opacity-40 grayscale";
                    }}
                }}

                htmlStr += `
                    <button onclick="choose('${{letter}}')" ${{showResult? 'disabled' : ''}} 
                            class="btn-physical text-left p-4 md:p-5 rounded-2xl flex items-center transition-all duration-200 ${{btnClass}} group">
                        ${{icon}} <span class="font-bold text-lg md:text-xl flex-1">${{opt.substring(2)}}</span>
                    </button>`;
            }});
            
            htmlStr += `</div></div>`;

            // 解析展示区
            if (answered[cur]!== null && q.explanation) {{
                const isCorrect = answered[cur] === q.answer;
                const expBg = isCorrect? 'bg-emerald-50 border-emerald-200' : 'bg-rose-50 border-rose-200';
                const expTitle = isCorrect? '<i class="fa-solid fa-award text-emerald-500 mr-2 text-xl"></i>知识点印证' : '<i class="fa-solid fa-triangle-exclamation text-rose-500 mr-2 text-xl"></i>知识点勘误';
                
                htmlStr += `
                    <div class="mt-8 p-6 rounded-2xl border-2 ${{expBg}} gsap-exp-pop relative overflow-hidden">
                        <div class="absolute top-0 left-0 w-2 h-full ${{isCorrect? 'bg-emerald-400' : 'bg-rose-400'}}"></div>
                        <h4 class="font-extrabold text-xl mb-3 ${{isCorrect? 'text-emerald-800' : 'text-rose-800'}}">${{expTitle}}</h4>
                        <p class="text-slate-700 font-semibold text-lg leading-relaxed">${{q.explanation}}</p>
                    </div>`;
            }}

            container.innerHTML = htmlStr;
            
            // GSAP 页面切入物理动画
            gsap.from(".gsap-quiz-entry", {{y: 30, opacity: 0, duration: 0.5, ease: "back.out(1.2)"}});
            if (document.querySelector('.gsap-exp-pop')) {{
                gsap.from(".gsap-exp-pop", {{scale: 0.95, opacity: 0, duration: 0.4, delay: 0.1, ease: "elastic.out(1, 0.7)"}});
            }}

            // 状态栏更新同步
            document.getElementById('q-counter').innerText = cur + 1;
            document.getElementById('progress-bar').style.width = `${{((cur + 1) / questions.length) * 100}}%`;
            document.getElementById('btn-prev').classList.toggle('hidden', cur === 0);
            
            const btnNext = document.getElementById('btn-next');
            if (cur === questions.length - 1) {{
                btnNext.innerHTML = '查收评级报告 <i class="fa-solid fa-flag-checkered ml-2"></i>';
                btnNext.className = "btn-physical px-10 py-4 rounded-2xl font-black text-white bg-amber-500 border-none shadow-duo-warning hover:bg-amber-400 text-lg";
            }} else {{
                btnNext.innerHTML = '继续挑战 <i class="fa-solid fa-arrow-right ml-2"></i>';
                btnNext.className = "btn-physical px-10 py-4 rounded-2xl font-black text-white bg-duo-primary border-none shadow-duo-primary hover:bg-[#61df02] text-lg";
            }}
        }}

        // 决策捕获逻辑
        window.choose = function(letter) {{
            if (answered[cur]!== null) return;
            answered[cur] = letter;
            
            const isCorrect = letter === questions[cur].answer;
            if (isCorrect) score += 150; // 夸大数值，增加多巴胺反馈
            
            // GSAP 积分滚动效果
            gsap.to("#score", {{
                innerHTML: score,
                duration: 0.5,
                snap: {{ innerHTML: 1 }},
                onUpdate: function() {{ document.getElementById('score').innerText = Math.round(this.targets().innerHTML); }}
            }});
            
            if(!isCorrect) {{
                // 错误：执行挫折震动反馈
                gsap.to(".glass-stage", {{x: [-12, 12, -8, 8, -4, 4, 0], duration: 0.5, ease: "power2.inOut"}});
            }} else {{
                // 正确：触发粒子礼花
                confetti({{ particleCount: 60, spread: 80, origin: {{ y: 0.7 }}, colors: ['#58cc02', '#1cb0f6', '#ffc800'] }});
            }}
            renderQ();
        }}

        window.nav = function(dir) {{
            if (cur + dir >= questions.length) {{
                finishGame(); return;
            }}
            cur += dir;
            renderQ();
        }}

        function finishGame() {{
            const percentage = Math.round((score / (questions.length * 150)) * 100);
            let msg = percentage >= 80? '你表现出了惊人的学习潜力，核心知识点掌握极佳！' : '遇到了一点挑战，不要灰心，多次练习能建立更强的神经元连接！';
            
            if(percentage >= 80) {{
                const duration = 4000; const end = Date.now() + duration;
                (function frame() {{
                    confetti({{ particleCount: 8, angle: 60, spread: 55, origin: {{ x: 0 }}, colors: ['#58cc02'] }});
                    confetti({{ particleCount: 8, angle: 120, spread: 55, origin: {{ x: 1 }}, colors: ['#1cb0f6'] }});
                    if (Date.now() < end) requestAnimationFrame(frame);
                }}());
            }}

            Swal.fire({{
                title: `击败了预期的 ${{percentage}}%！`,
                text: msg,
                icon: percentage >= 80? 'success' : 'info',
                confirmButtonText: '重置并再次挑战',
                confirmButtonColor: '#58cc02',
                background: '#ffffff',
                backdrop: `rgba(15, 23, 42, 0.85)`
            }}).then((result) => {{
                if (result.isConfirmed) {{
                    cur = 0; score = 0; answered.fill(null);
                    document.getElementById('score').innerText = '0';
                    renderQ();
                }}
            }});
        }}

        renderQ();
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 2: 图谱连线配对 (Matching)
# ==========================================
def render_matching(data: dict) -> str:
    title = html.escape(data.get("title", "概念链路图配对"))
    pairs_json = json.dumps(data.get("pairs",), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <p class="text-center text-slate-500 mb-8 font-bold text-lg"><i class="fa-solid fa-link text-edtech-500 mr-2"></i>建立神经映射：点击左侧概念原点，将其锚定至右侧确切定义</p>
        
        <div class="flex justify-center items-center mb-10 bg-slate-50 p-4 rounded-2xl border-2 border-slate-100">
            <span class="text-slate-500 font-extrabold text-xl">已构建链接: <span id="match-count" class="text-edtech-500 text-2xl mx-2">0</span> / <span id="total-count" class="text-2xl"></span></span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-12 md:gap-24 relative min-h-[400px] p-4" id="match-container">
            <svg id="lines-svg" class="absolute top-0 left-0 w-full h-full pointer-events-none z-0" style="overflow: visible;"></svg>
            
            <div id="col-left" class="flex flex-col space-y-6 z-10"></div>
            <div id="col-right" class="flex flex-col space-y-6 z-10"></div>
        </div>

    <script>
        const pairs = {pairs_json};
        document.getElementById('total-count').innerText = pairs.length;
        
        // 采用洗牌算法打乱阵列
        const shuffle = arr => arr.map(a => ([Math.random(), a])).sort((a, b) => a - b).map(a => a);
        
        const leftItems = shuffle(pairs.map((p, i) => ({{id: i, text: p.concept}})));
        const rightItems = shuffle(pairs.map((p, i) => ({{id: i, text: p.definition}})));
        
        let selectedLeft = null;
        let matchedCount = 0;
        const matchedIds = new Set();

        function createCard(item, side) {{
            const div = document.createElement('div');
            div.className = `btn-physical p-5 rounded-2xl border-2 border-slate-200 bg-white shadow-duo-soft cursor-pointer font-extrabold text-center text-slate-700 text-lg transition-all duration-200 hover:border-edtech-300`;
            div.id = `${{side}}-${{item.id}}`;
            div.innerText = item.text;
            div.onclick = () => handleSelect(item.id, side, div);
            return div;
        }}

        function init() {{
            const colL = document.getElementById('col-left');
            const colR = document.getElementById('col-right');
            leftItems.forEach(item => colL.appendChild(createCard(item, 'left')));
            rightItems.forEach(item => colR.appendChild(createCard(item, 'right')));
            
            // 空间飞入动效
            gsap.from("#col-left div", {{x: -80, opacity: 0, stagger: 0.1, duration: 0.6, ease: "back.out(1.4)"}});
            gsap.from("#col-right div", {{x: 80, opacity: 0, stagger: 0.1, duration: 0.6, ease: "back.out(1.4)"}});
            
            // 监听窗口缩放重绘SVG线
            window.addEventListener('resize', redrawLines);
        }}

        function handleSelect(id, side, el) {{
            if (matchedIds.has(id)) return;

            if (side === 'left') {{
                // 重置先前选择
                if (selectedLeft!== null &&!matchedIds.has(selectedLeft)) {{
                    document.getElementById(`left-${{selectedLeft}}`).classList.remove('border-edtech-500', 'bg-[#e0f2fe]', 'text-edtech-700', 'shadow-[0_4px_0_0_#0284c7]');
                }}
                selectedLeft = id;
                // 激活态渲染
                el.classList.add('border-edtech-500', 'bg-[#e0f2fe]', 'text-edtech-700', 'shadow-[0_4px_0_0_#0284c7]');
                gsap.fromTo(el, {{scale: 0.95}}, {{scale: 1, duration: 0.3, ease: "elastic.out(1, 0.4)"}});
            }} 
            else if (side === 'right' && selectedLeft!== null) {{
                const leftEl = document.getElementById(`left-${{selectedLeft}}`);
                const rightEl = el;

                if (selectedLeft === id) {{
                    // 匹配成功
                    matchedIds.add(id);
                    matchedCount++;
                    document.getElementById('match-count').innerText = matchedCount;
                    
                    // 修改为成功锁定态
                    [leftEl, rightEl].forEach(e => {{
                        e.className = 'p-5 rounded-2xl border-2 border-emerald-400 bg-emerald-50 text-emerald-700 font-extrabold text-center text-lg opacity-60 cursor-default';
                        e.style.transform = 'translateY(4px)'; // 保持按压陷入状态
                    }});
                    
                    drawLine(leftEl, rightEl, id);
                    
                    // 微小粒子反馈
                    const rect = rightEl.getBoundingClientRect();
                    confetti({{ particleCount: 40, spread: 50, origin: {{ x: (rect.left + rect.width/2)/window.innerWidth, y: rect.top/window.innerHeight }}, colors: ['#10b981'] }});

                    selectedLeft = null;

                    if (matchedCount === pairs.length) {{
                        setTimeout(() => {{
                            Swal.fire({{ title: '知识链路重构完毕！', icon: 'success', confirmButtonColor: '#58cc02' }});
                        }}, 600);
                    }}
                }} else {{
                    // 匹配失败物理震动
                    gsap.to([leftEl, rightEl], {{x: [-15, 15, -10, 10, -5, 5, 0], duration: 0.5, ease: "power1.inOut"}});
                    leftEl.classList.remove('border-edtech-500', 'bg-[#e0f2fe]', 'text-edtech-700', 'shadow-[0_4px_0_0_#0284c7]');
                    selectedLeft = null;
                }}
            }}
        }}

        // SVG 绝对坐标计算与绘制
        function drawLine(el1, el2, id) {{
            const svg = document.getElementById('lines-svg');
            const rect1 = el1.getBoundingClientRect();
            const rect2 = el2.getBoundingClientRect();
            const svgRect = svg.getBoundingClientRect();
            
            const x1 = rect1.right - svgRect.left;
            const y1 = rect1.top + rect1.height / 2 - svgRect.top;
            const x2 = rect2.left - svgRect.left;
            const y2 = rect2.top + rect2.height / 2 - svgRect.top;

            let line = document.getElementById(`line-${{id}}`);
            if(!line) {{
                line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                line.id = `line-${{id}}`;
                line.setAttribute('stroke', '#10b981');
                line.setAttribute('stroke-width', '4');
                line.setAttribute('stroke-dasharray', '8,6');
                line.setAttribute('stroke-linecap', 'round');
                line.setAttribute('fill', 'none');
                line.style.opacity = '0.6';
                svg.appendChild(line);
                
                // 绘制动画
                const length = Math.sqrt(Math.pow(x2-x1, 2) + Math.pow(y2-y1, 2));
                gsap.fromTo(line, {{strokeDashoffset: length}}, {{strokeDashoffset: 0, duration: 0.5, ease: "power2.out"}});
            }}
            
            // 绘制平滑的三次贝塞尔曲线 (Cubic Bezier)
            const cx = (x1 + x2) / 2;
            line.setAttribute('d', `M ${{x1}} ${{y1}} C ${{cx}} ${{y1}}, ${{cx}} ${{y2}}, ${{x2}} ${{y2}}`);
        }}

        function redrawLines() {{
            matchedIds.forEach(id => {{
                const el1 = document.getElementById(`left-${{id}}`);
                const el2 = document.getElementById(`right-${{id}}`);
                if(el1 && el2) drawLine(el1, el2, id);
            }});
        }}

        init();
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 3: 拖拽排序 (Sorting)
# ==========================================
def render_sorting(data: dict) -> str:
    title = html.escape(data.get("title", "逻辑序列重构"))
    # 处理容错，支持 tasks 或 items
    items = data.get("tasks", data.get("items",))
    items_json = json.dumps(items, ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <p class="text-center text-slate-500 mb-8 font-bold text-lg"><i class="fa-solid fa-arrows-up-down text-edtech-500 mr-2"></i>对卡片进行长按并上下拖拽，使其符合正确的客观逻辑序列</p>
        
        <ul id="sortable-list" class="space-y-4 mb-10 mx-auto max-w-2xl"></ul>
        
        <div class="flex justify-center">
            <button id="verify-btn" class="btn-physical px-12 py-4 rounded-2xl font-black text-white bg-duo-primary border-none shadow-duo-primary hover:bg-[#61df02] text-xl tracking-wide w-full md:w-auto" onclick="verifyOrder()">
                递交校验引擎 <i class="fa-solid fa-shield-halved ml-2"></i>
            </button>
        </div>

    <script>
        const correctItems = {items_json};
        
        // 初始装载打乱数组
        let currentItems = [...correctItems].map((item, index) => ({{ text: item, originalIndex: index }}));
        currentItems.sort(() => Math.random() - 0.5);

        const listEl = document.getElementById('sortable-list');
        
        currentItems.forEach((item, displayIndex) => {{
            const li = document.createElement('li');
            li.className = "p-5 rounded-2xl bg-white border-2 border-slate-200 shadow-sm cursor-grab flex items-center group transition-colors hover:border-edtech-400";
            li.dataset.orig = item.originalIndex;
            li.innerHTML = `
                <div class="mr-5 text-slate-300 group-hover:text-edtech-500 transition-colors"><i class="fa-solid fa-grip-vertical text-2xl"></i></div>
                <div class="font-extrabold text-slate-700 text-lg select-none flex-1">${{item.text}}</div>
            `;
            listEl.appendChild(li);
        }});

        // 实例化原生拖拽库 SortableJS [23, 24]
        new Sortable(listEl, {{
            animation: 250, // 毫秒平滑过渡
            ghostClass: 'opacity-0', // 隐藏原始占位符
            dragClass: 'shadow-2xl', // 拖拽悬浮阴影放大
            easing: "cubic-bezier(0.2, 0, 0, 1)"
        }});

        window.verifyOrder = function() {{
            const currentOrder = Array.from(listEl.children).map(li => parseInt(li.dataset.orig));
            let isCorrect = true;
            
            // 严格验证序列递增
            for(let i=0; i<currentOrder.length; i++) {{
                if(currentOrder[i]!== i) {{
                    isCorrect = false; break;
                }}
            }}

            if(isCorrect) {{
                confetti({{ particleCount: 150, spread: 80, origin: {{ y: 0.6 }}, colors: ['#58cc02', '#0ea5e9'] }});
                Swal.fire({{ title:'完美秩序！', text:'排列序列逻辑完全正确！', icon:'success', confirmButtonColor: '#58cc02' }});
                document.getElementById('verify-btn').disabled = true;
                document.getElementById('verify-btn').classList.add('opacity-40', 'grayscale');
                Array.from(listEl.children).forEach(li => {{
                    li.classList.replace('border-slate-200', 'border-emerald-400');
                    li.classList.add('bg-emerald-50');
                }});
            }} else {{
                gsap.to("#sortable-list", {{x: [-15, 15, -10, 10, -5, 5, 0], duration: 0.5, ease: "power2.inOut"}});
                Swal.fire({{ title:'熵值过高', text:'部分环节次序存在逻辑冲突，请重新审视。', icon:'error', confirmButtonColor: '#dc2626' }});
            }}
        }}
        
        // 初始瀑布流落入动效
        gsap.from("#sortable-list li", {{y: 40, opacity: 0, stagger: 0.08, duration: 0.6, ease: "back.out(1.2)"}});
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 4: 填空题 (Fill-in-the-blank)
# ==========================================
def render_fillblank(data: dict) -> str:
    title = html.escape(data.get("title", "深度填空测试"))
    q_json = json.dumps(data.get("questions",), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <p class="text-center text-slate-500 mb-8 font-bold text-lg"><i class="fa-solid fa-keyboard text-edtech-500 mr-2"></i>在对应横线处键入精确的学术名词或参数</p>
        
        <div id="fb-container" class="space-y-8 mb-10 mx-auto max-w-3xl"></div>
        
        <div class="flex justify-center">
            <button class="btn-physical px-12 py-4 rounded-2xl font-black text-white bg-purple-600 border-none shadow-[0_5px_0_0_#9333ea] hover:bg-purple-500 text-xl tracking-wide w-full md:w-auto" onclick="submitAll()">
                提交全卷审阅 <i class="fa-solid fa-paper-plane ml-2"></i>
            </button>
        </div>

    <script>
        const questions = {q_json};
        const container = document.getElementById('fb-container');
        
        questions.forEach((q, qi) => {{
            // 提取下划线占位符 
            const parts = q.sentence.split('____');
            let htmlStr = `<div class="p-8 rounded-3xl bg-white border-2 border-slate-200 shadow-sm fb-card relative overflow-hidden group">
                           <div class="absolute top-0 left-0 w-1.5 h-full bg-slate-200 group-hover:bg-edtech-400 transition-colors"></div>`;
            htmlStr += `<div class="text-xl font-bold text-slate-700 leading-[2.5rem] ml-4">`;
            
            for(let i=0; i<parts.length; i++) {{
                htmlStr += parts[i];
                if(i < parts.length - 1) {{
                    // 内联输入框设计，提升填写语境感知
                    htmlStr += `<input type="text" id="fill-${{qi}}-${{i}}" class="mx-3 inline-block w-40 border-b-4 border-slate-300 bg-slate-50 text-center font-black text-edtech-600 text-xl focus:outline-none focus:border-edtech-500 focus:bg-edtech-50 transition-colors py-1">`;
                }}
            }}
            htmlStr += `</div>`;
            
            if(q.hint) {{
                htmlStr += `<div class="mt-6 ml-4 text-sm font-bold text-amber-600 bg-amber-50 p-3 rounded-xl inline-flex items-center"><i class="fa-regular fa-lightbulb text-lg mr-2"></i>线索前瞻：${{q.hint}}</div>`;
            }}
            htmlStr += `<div id="fb-feedback-${{qi}}" class="mt-5 ml-4 hidden"></div></div>`;
            container.innerHTML += htmlStr;
        }});

        gsap.from(".fb-card", {{y: 30, opacity: 0, stagger: 0.15, duration: 0.6, ease: "power2.out"}});

        window.submitAll = function() {{
            let allCorrect = true;
            
            questions.forEach((q, qi) => {{
                let qCorrect = true;
                for(let i=0; i<q.blanks.length; i++) {{
                    const input = document.getElementById(`fill-${{qi}}-${{i}}`);
                    const userVal = input.value.trim();
                    const ans = q.blanks[i];
                    
                    // 柔性匹配逻辑：允许包含关系 
                    if(userVal!== '' && (userVal === ans |

| ans.includes(userVal) |
| userVal.includes(ans))) {{
                        input.classList.replace('border-slate-300', 'border-emerald-500');
                        input.classList.add('bg-emerald-50', 'text-emerald-700');
                    }} else {{
                        input.classList.replace('border-slate-300', 'border-rose-500');
                        input.classList.add('bg-rose-50', 'text-rose-700');
                        qCorrect = false;
                        allCorrect = false;
                    }}
                    input.disabled = true;
                }}
                
                const fb = document.getElementById(`fb-feedback-${{qi}}`);
                fb.classList.remove('hidden');
                if(qCorrect) {{
                    fb.innerHTML = '<div class="p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl text-emerald-700 font-extrabold"><i class="fa-solid fa-circle-check mr-2"></i> 逻辑推演完全正确</div>';
                }} else {{
                    fb.innerHTML = `<div class="p-4 bg-rose-50 border-2 border-rose-200 rounded-xl text-rose-700 font-extrabold"><i class="fa-solid fa-circle-xmark mr-2"></i> 标准参照元数据: <span class="underline decoration-wavy ml-1">${{q.blanks.join(' / ')}}</span></div>`;
                }}
            }});

            if(allCorrect) {{
                confetti({{ particleCount: 120, spread: 90, origin: {{ y: 0.5 }} }});
                Swal.fire('学术级准度！', '所有核心数据点均填补正确！', 'success');
            }} else {{
                Swal.fire('存在偏差', '请对照下方红色标识的参照元数据进行复盘。', 'warning');
            }}
        }}
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 5: 判断题 (True / False)
# ==========================================
def render_tf(data: dict) -> str:
    title = html.escape(data.get("title", "二元判断挑战"))
    q_json = json.dumps(data.get("questions",), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <div class="flex justify-center items-center mb-10 bg-slate-50 p-4 rounded-2xl border-2 border-slate-100">
            <span class="text-slate-500 font-extrabold text-xl">探案阶段 <span id="tf-cur" class="text-edtech-600 text-2xl mx-1">1</span> / <span id="tf-tot" class="text-2xl"></span></span>
        </div>

        <div id="tf-card" class="bg-white border-2 border-slate-200 rounded-[2.5rem] p-12 shadow-xl text-center min-h-[300px] flex flex-col justify-center items-center relative overflow-hidden mx-auto max-w-2xl">
            <div class="absolute -top-10 -right-10 opacity-5 text-9xl"><i class="fa-solid fa-scale-balanced"></i></div>
            <h2 id="tf-stem" class="text-3xl md:text-4xl font-black text-slate-800 leading-tight z-10"></h2>
        </div>

        <div class="grid grid-cols-2 gap-6 md:gap-10 mt-12 mx-auto max-w-2xl">
            <button class="btn-physical py-8 rounded-3xl font-black text-white bg-rose-500 shadow-[0_6px_0_0_#dc2626] hover:bg-rose-400 text-3xl" onclick="answerTF(false)">
                <i class="fa-solid fa-xmark mr-3"></i> 证伪
            </button>
            <button class="btn-physical py-8 rounded-3xl font-black text-white bg-emerald-500 shadow-[0_6px_0_0_#16a34a] hover:bg-emerald-400 text-3xl" onclick="answerTF(true)">
                <i class="fa-solid fa-check mr-3"></i> 证实
            </button>
        </div>

    <script>
        const questions = {q_json};
        let cur = 0; let score = 0;
        document.getElementById('tf-tot').innerText = questions.length;

        function renderTF() {{
            document.getElementById('tf-cur').innerText = cur + 1;
            document.getElementById('tf-stem').innerText = questions[cur].stem;
            
            // T/F 题干卡片弹入动效
            gsap.fromTo("#tf-card", {{scale: 0.7, opacity: 0, rotation: -2}}, {{scale: 1, opacity: 1, rotation: 0, duration: 0.6, ease: "elastic.out(1, 0.6)"}});
        }}

        window.answerTF = function(userChoice) {{
            const isCorrect = userChoice === questions[cur].answer;
            
            if(isCorrect) {{
                score++;
                // 正确：向右横扫飞出
                gsap.to("#tf-card", {{x: window.innerWidth, rotation: 15, opacity: 0, duration: 0.4, ease: "power2.in", onComplete: nextQ}});
            }} else {{
                // 错误：猛烈震动后向左下落败退场
                const tl = gsap.timeline();
                tl.to("#tf-card", {{x: [-20, 20, -15, 15, -10, 10, 0], duration: 0.4}});
                tl.to("#tf-card", {{y: 200, rotation: -15, opacity: 0, duration: 0.4, ease: "power2.in", onComplete: nextQ}});
            }}
        }}

        function nextQ() {{
            cur++;
            gsap.set("#tf-card", {{x: 0, y: 0, rotation: 0}}); // 充权重置卡片物理状态
            if(cur >= questions.length) {{
                let msg = score === questions.length? '全部论点均被精准判定，逻辑坚不可摧！' : `成功证实了 ${{score}} / ${{questions.length}} 个论点。`;
                if (score === questions.length) confetti({{ particleCount: 200, spread: 100, origin:{{y:0.3}} }});
                
                Swal.fire({{
                    title: '判决终结', text: msg, icon: score === questions.length? 'success' : 'info',
                    confirmButtonText: '重启判决引擎', confirmButtonColor: '#0ea5e9'
                }}).then(() => {{ cur = 0; score = 0; renderTF(); }});
            }} else {{ renderTF(); }}
        }}
        renderTF();
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 6: 翻卡记忆 (Flashcard - CSS 3D Space)
# ==========================================
def render_flashcard(data: dict) -> str:
    title = html.escape(data.get("title", "知识矩阵闪卡记忆"))
    cards_json = json.dumps(data.get("cards",), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <p class="text-center text-slate-500 mb-8 font-bold text-lg"><i class="fa-solid fa-cube text-edtech-500 mr-2"></i>点击卡片进行多维空间翻转，揭示底层释义</p>
        
        <div class="flex justify-between items-center mb-8 bg-slate-50 p-4 rounded-2xl border-2 border-slate-100">
            <span class="text-slate-500 font-extrabold text-lg"><i class="fa-solid fa-brain text-emerald-500 mr-2"></i>已攻克: <span id="fc-mastered" class="text-emerald-600 text-xl mx-1">0</span></span>
            <span class="text-slate-500 font-extrabold text-lg"><i class="fa-solid fa-layer-group text-edtech-500 mr-2"></i>列阵: <span id="fc-cur" class="text-edtech-600 text-xl mx-1">1</span> / <span id="fc-tot"></span></span>
        </div>

        <div class="relative w-full h-[350px] mx-auto max-w-2xl cursor-pointer group mb-10" style="perspective: 1200px;" onclick="flip()">
            <div id="fc-inner" class="w-full h-full relative transition-transform duration-[800ms] ease-[cubic-bezier(0.175,0.885,0.32,1.275)]" style="transform-style: preserve-3d;">
                
                <div class="absolute w-full h-full bg-white border-2 border-slate-200 rounded-[2.5rem] shadow-xl flex items-center justify-center p-10 z-20" style="backface-visibility: hidden;">
                    <h2 id="fc-front-text" class="text-4xl md:text-5xl font-black text-slate-800 text-center"></h2>
                </div>
                
                <div class="absolute w-full h-full bg-gradient-to-br from-indigo-50 to-blue-100 border-2 border-indigo-200 rounded-[2.5rem] shadow-xl flex items-center justify-center p-10 z-10" style="backface-visibility: hidden; transform: rotateY(180deg);">
                    <p id="fc-back-text" class="text-2xl font-extrabold text-indigo-900 text-center leading-loose"></p>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-6 mx-auto max-w-2xl">
            <button class="btn-physical py-5 rounded-2xl font-black text-amber-600 bg-amber-50 border-2 border-amber-300 shadow-[0_5px_0_0_#fcd34d] hover:bg-amber-100 text-xl" onclick="mark(false)">
                <i class="fa-solid fa-clock-rotate-left mr-2"></i>遗忘 / 重构
            </button>
            <button class="btn-physical py-5 rounded-2xl font-black text-emerald-600 bg-emerald-50 border-2 border-emerald-300 shadow-[0_5px_0_0_#86efac] hover:bg-emerald-100 text-xl" onclick="mark(true)">
                <i class="fa-solid fa-check-double mr-2"></i>已彻底攻克
            </button>
        </div>

    <script>
        const cards = {cards_json};
        let cur = 0; let isFlipped = false;
        const mastered = new Set();
        document.getElementById('fc-tot').innerText = cards.length;

        function renderCard() {{
            document.getElementById('fc-cur').innerText = cur + 1;
            document.getElementById('fc-mastered').innerText = mastered.size;
            document.getElementById('fc-front-text').innerText = cards[cur].front;
            document.getElementById('fc-back-text').innerText = cards[cur].back;
            
            const inner = document.getElementById('fc-inner');
            inner.style.transform = 'rotateY(0deg)'; // 状态重置
            isFlipped = false;
            
            gsap.fromTo(inner, {{scale: 0.8, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.5, ease: "back.out(1.2)"}});
        }}

        window.flip = function() {{
            isFlipped =!isFlipped;
            // 触发 3D 旋转
            document.getElementById('fc-inner').style.transform = isFlipped? 'rotateY(180deg)' : 'rotateY(0deg)';
        }}

        window.mark = function(isMastered) {{
            if(isMastered) mastered.add(cur);
            else mastered.delete(cur); // 移出掌握集合 
            
            if(mastered.size === cards.length) {{
                document.getElementById('fc-mastered').innerText = mastered.size;
                confetti({{ particleCount: 150, spread: 90, origin: {{y: 0.4}} }});
                Swal.fire('神经元矩阵重塑完成', '当前词库所有节点已全部攻克写入长期记忆！', 'success').then(() => {{
                    mastered.clear(); cur = 0; renderCard();
                }});
                return;
            }}
            // 顺序遍历下一个（简化的学习流，可引入艾宾浩斯曲线）
            cur = (cur + 1) % cards.length;
            renderCard();
        }}
        renderCard();
    </script>
    """ + _FOOTER
    return html_content

# ==========================================
# 游戏 7: 流程补全 (Process Completion Flowfill)
# ==========================================
def render_flowfill(data: dict) -> str:
    title = html.escape(data.get("title", "系统流程架构补全"))
    flow_data = json.dumps(data.get("flow", {}), ensure_ascii=False)
    
    html_content = _HEAD.format(title=title) + f"""
        <p class="text-center text-slate-500 mb-8 font-bold text-lg"><i class="fa-solid fa-diagram-project text-edtech-500 mr-2"></i>点击下方参数库选项，将其加载至虚线框槽位以闭环整个系统流程</p>
        
        <div class="flex flex-col md:flex-row gap-8 w-full">
            <div id="flow-container" class="flex flex-col items-center space-y-3 mb-8 w-full md:w-2/3 bg-slate-50 p-8 rounded-3xl border-2 border-slate-100"></div>
            
            <div class="w-full md:w-1/3 flex flex-col gap-6">
                <div class="bg-white p-6 rounded-3xl border-2 border-slate-200 shadow-lg">
                    <h3 class="text-sm font-black text-slate-400 mb-6 uppercase tracking-widest text-center border-b-2 border-slate-100 pb-3"><i class="fa-solid fa-database mr-2"></i>参数选项库 (Options)</h3>
                    <div id="options-bank" class="flex flex-wrap justify-center gap-4"></div>
                </div>
                <button class="btn-physical py-5 rounded-2xl font-black text-white bg-duo-primary shadow-duo-primary hover:bg-[#61df02] text-xl w-full" onclick="checkCompletion()">
                    运行闭环校验 <i class="fa-solid fa-play ml-2"></i>
                </button>
            </div>
        </div>

    <script>
        const flowData = {flow_data};
        const nodes = flowData.nodes |

|;
        const blanksDict = flowData.blank_answers |

| {{}};
        
        let selectedOpt = null;
        const userAnswers = {{}};
        
        // 提取正确答案并洗牌混淆
        const optionsList = Object.values(blanksDict).sort(() => Math.random() - 0.5);

        function render() {{
            const container = document.getElementById('flow-container');
            container.innerHTML = '';
            
            nodes.forEach((node, idx) => {{
                const div = document.createElement('div');
                if(!node.is_blank) {{
                    div.className = "px-8 py-5 bg-indigo-600 text-white font-extrabold rounded-2xl shadow-lg w-full max-w-sm text-center z-10 text-xl border-b-4 border-indigo-800";
                    div.innerText = node.label;
                }} else {{
                    const filledVal = userAnswers[node.id];
                    // 状态驱动的 CSS 类切换 
                    div.className = `px-8 py-5 font-extrabold rounded-2xl w-full max-w-sm text-center cursor-pointer transition-all duration-300 z-10 border-4 border-dashed text-xl ${{filledVal? 'bg-amber-50 border-amber-400 text-amber-700 shadow-md' : 'bg-slate-100 border-slate-300 text-slate-400 hover:border-edtech-400 hover:bg-white' }}`;
                    div.innerText = filledVal? filledVal : '【 空置槽位 】';
                    div.onclick = () => {{
                        if(selectedOpt) {{
                            userAnswers[node.id] = selectedOpt;
                            selectedOpt = null; // 清空光标手持状态
                            render();
                        }}
                    }};
                }}
                container.appendChild(div);
                
                // 渲染导向箭头
                if(idx < nodes.length - 1) {{
                    const arrow = document.createElement('div');
                    arrow.className = "text-slate-300 text-3xl my-[-8px] z-0";
                    arrow.innerHTML = '<i class="fa-solid fa-arrow-down-long"></i>';
                    container.appendChild(arrow);
                }}
            }});

            const bank = document.getElementById('options-bank');
            bank.innerHTML = '';
            
            optionsList.forEach(opt => {{
                const isUsed = Object.values(userAnswers).includes(opt);
                const isSelected = selectedOpt === opt;
                
                const btn = document.createElement('button');
                let baseClass = "px-5 py-3 font-bold rounded-xl transition-all duration-200 text-lg ";
                
                if(isUsed) {{
                    btn.className = baseClass + "bg-slate-100 text-slate-400 opacity-40 cursor-not-allowed border-2 border-slate-200";
                }} else if(isSelected) {{
                    btn.className = baseClass + "bg-amber-400 text-white shadow-[0_4px_0_0_#b45309] border-2 border-amber-400 transform -translate-y-1";
                }} else {{
                    btn.className = baseClass + "bg-white text-slate-700 border-2 border-slate-200 shadow-[0_4px_0_0_#cbd5e1] hover:bg-slate-50 active:translate-y-1 active:shadow-none";
                }}
                
                btn.innerText = opt;
                if(!isUsed) {{
                    btn.onclick = () => {{
                        selectedOpt = selectedOpt === opt? null : opt; // 切换光标吸附状态
                        render();
                    }};
                }}
                bank.appendChild(btn);
            }});
        }}

        // 校验引擎逻辑
        window.checkCompletion = function() {{
            const blankIds = Object.keys(blanksDict);
            const filledCount = Object.keys(userAnswers).length;
            
            if(filledCount < blankIds.length) {{
                Swal.fire('链路阻断', '存在空置槽位未填补，系统无法运行闭环测试。', 'warning');
                return;
            }}

            let isCorrect = true;
            blankIds.forEach(id => {{ if(userAnswers[id]!== blanksDict[id]) isCorrect = false; }});
            
            if(isCorrect) {{
                confetti({{ particleCount: 150, spread: 100, origin: {{ y: 0.5 }} }});
                Swal.fire('系统跑通！', '流程架构逻辑严密，无任何运行时冲突！', 'success');
            }} else {{
                gsap.to("#flow-container", {{x: [-15, 15, -10, 10, -5, 5, 0], duration: 0.5}});
                Swal.fire('致命错误', '节点参数错位，导致流程链条崩溃，请排查重组。', 'error').then(() => {{
                    for(let key in userAnswers) delete userAnswers[key]; // 清空重置
                    selectedOpt = null;
                    render();
                }});
            }}
        }}

        render();
        gsap.from("#flow-container > div", {{y: 30, opacity: 0, stagger: 0.1, duration: 0.6, ease: "back.out(1.2)"}});
    </script>
    """ + _FOOTER
    return html_content


# ── Registry: GameType → renderer function ──
GAME_RENDERERS = {
    "quiz": render_quiz,
    "matching": render_matching,
    "sorting": render_sorting,
    "fill_blank": render_fillblank,
    "true_false": render_tf,
    "flashcard": render_flashcard,
    "flow_fill": render_flowfill,
}
