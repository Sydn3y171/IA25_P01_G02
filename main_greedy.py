# Horários — Construtor determinista (primeira solução), com melhorias opcionais
# - Lê ClassTT_01_tiny.txt
# - Gera a primeira solução válida sem overlaps de docente/turma e com UC_1 < UC_2
# - Opcional: split-week (UC_1 em 1..10, UC_2 em 11..20)
# - Exporta CSV + PNG/PDF
# - Melhorias opcionais (sem alterar o default):
#     --shuffle: baralha ordem das variáveis
#     --restarts N: faz múltiplas tentativas (útil com --shuffle)
#     --heuristic {none,mrv,degree,mrv-degree}: ordenação informada das variáveis

import argparse, pathlib, re, os, hashlib, colorsys, random
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Optional, Iterable

import pandas as pd

import matplotlib
matplotlib.use("Agg")  # render sem janela
import matplotlib.pyplot as plt

# Base calendário 
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
BLOCKS_PER_DAY = 4
SLOTS = list(range(1, 5 * BLOCKS_PER_DAY + 1))  # 1..20
BLOCK_LABELS = ["B1", "B2", "B3", "B4"]
BLOCK_TO_TIME = {
    "B1": ("09:00", "11:00"),
    "B2": ("11:00", "13:00"),
    "B3": ("14:00", "16:00"),
    "B4": ("16:00", "18:00"),
}
BLOCK_TO_TIME_STR = {k: f"{a}–{b}" for k, (a, b) in BLOCK_TO_TIME.items()}

def slot_day(slot: int) -> str:
    # Dado um índice de slot (1..20), devolve o dia da semana.
    return DAYS[(slot - 1) // BLOCKS_PER_DAY]

def slot_to_day_and_block(slot: int) -> Tuple[str, str]:
    # Converte slot absoluto (1..20) para (dia, bloco B1..B4).
    day_idx = (slot - 1) // BLOCKS_PER_DAY
    block_idx = (slot - 1) % BLOCKS_PER_DAY
    return DAYS[day_idx], BLOCK_LABELS[block_idx]

# Parse dataset 
def read_section(raw: str, tag: str) -> List[str]:
    
    # Extrai uma secção do ficheiro de dados, marcada por '#tag'.
    # Retorna as linhas (já limpas) dessa secção.
    
    pat = re.compile(rf"#{tag}[^\n]*\n(.*?)(?=\n#|$)", re.S)
    m = pat.search(raw)
    return [] if not m else [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]

def load_dataset(path: str) -> Dict:
    
    # Carrega e estrutura o dataset.
    # Estruturas principais:
    #   - class_to_ucs: turma -> [UCs]
    #   - teacher_to_ucs: docente -> [UCs]
    #   - teacher_unavail: docente -> {slots indisponíveis}
    #   - uc_room_required: UC -> sala (apenas para output)
    #   - uc_online_idx: UC -> {índices de aulas online} (1 ou 2)
    #   - uc_to_class, uc_to_teacher: UC -> turma / docente
    #   - UCs: lista ordenada de UCs
    
    raw = pathlib.Path(path).read_text(encoding="utf-8")

    cc   = read_section(raw, "cc")
    dsd  = read_section(raw, "dsd")
    tr   = read_section(raw, "tr")
    rr   = read_section(raw, "rr")
    oc   = read_section(raw, "oc")

    class_to_ucs = {}
    for ln in cc:
        parts = ln.split()
        class_to_ucs[parts[0]] = parts[1:]

    teacher_to_ucs = {}
    for ln in dsd:
        parts = ln.split()
        teacher_to_ucs[parts[0]] = parts[1:]

    teacher_unavail = {}
    for ln in tr:
        parts = ln.split()
        teacher_unavail[parts[0]] = set(map(int, parts[1:]))

    uc_room_required = {}
    for ln in rr:
        uc, room = ln.split()
        uc_room_required[uc] = room

    uc_online_idx = defaultdict(set)
    for ln in oc:
        # Garante NO MÁXIMO dois tokens por linha (#oc mal formatado rebenta domínios)
        uc, idx = ln.split()
        uc_online_idx[uc].add(int(idx))

    uc_to_class, uc_to_teacher = {}, {}
    for c, ucs in class_to_ucs.items():
        for uc in ucs: uc_to_class[uc] = c
    for t, ucs in teacher_to_ucs.items():
        for uc in ucs: uc_to_teacher[uc] = t

    UCs = sorted(uc_to_class.keys())
    return {
        "class_to_ucs": class_to_ucs,
        "teacher_to_ucs": teacher_to_ucs,
        "teacher_unavail": teacher_unavail,
        "uc_room_required": uc_room_required,
        "uc_online_idx": uc_online_idx,
        "uc_to_class": uc_to_class,
        "uc_to_teacher": uc_to_teacher,
        "UCs": UCs
    }

# Heurísticas
def build_var_list(data: Dict) -> List[str]:
    
    # Constrói a lista de variáveis no formato UC_1, UC_2, agrupadas por turma e UC.
    # Esta é a ordem "base" determinista.

    uc_to_class = data["uc_to_class"]
    base = []
    for turma in sorted(set(uc_to_class[uc] for uc in data["UCs"])):
        ucs = [uc for uc in data["UCs"] if uc_to_class[uc] == turma]
        for uc in sorted(ucs):
            base.append(f"{uc}_1")
            base.append(f"{uc}_2")
    return base

def candidate_slots_for_idx(idx: int, teacher: str, teacher_unav: Dict[str,set], split_week: bool) -> List[int]:
    
    # Domínio base de slots para uma aula #idx (1 ou 2) de uma UC com dado docente,
    # respeitando indisponibilidades e split-week (se ativo).
    
    bad = teacher_unav.get(teacher, set())
    if split_week:
        half = len(SLOTS)//2
        base = [s for s in SLOTS if (s <= half if idx == 1 else s > half)]
    else:
        base = SLOTS
    return [s for s in base if s not in bad]

def order_variables(vars_order: List[str],
                    data: Dict,
                    split_week: bool,
                    heuristic: str,
                    class_busy: Dict[str,set],
                    teacher_busy: Dict[str,set],
                    assigned: Dict[str, Tuple[int,str,str]]) -> List[str]:
    
    # Ordena as variáveis ainda não atribuídas com base numa heurística.
    # Heurísticas:
    #   - none: mantém a ordem recebida
    #   - degree: primeiro as que “constrangem” mais (docentes / turmas populares)
    #   - mrv: Minimum Remaining Values (menos slots legais neste momento)
    #   - mrv-degree: MRV com desempate por degree

    if heuristic == "none":
        return vars_order

    uc_to_teacher = data["uc_to_teacher"]
    uc_to_class   = data["uc_to_class"]
    teacher_unav  = data["teacher_unavail"]

    # Pré-cálculos para "degree": quantas variáveis competem pelo mesmo docente/turma
    deg_score = {}
    doc_counts = Counter(uc_to_teacher[ v.split("_")[0] ] for v in vars_order)
    class_counts = Counter(uc_to_class[ v.split("_")[0] ] for v in vars_order)
    for v in vars_order:
        uc = v.split("_")[0]
        deg_score[v] = doc_counts[uc_to_teacher[uc]] + class_counts[uc_to_class[uc]]

    # Cálculo MRV: quantos slots legais a variável tem neste momento
    def legal_count(v: str) -> int:
        uc, idx_s = v.split("_"); idx = int(idx_s)
        t = uc_to_teacher[uc]; c = uc_to_class[uc]
        base = candidate_slots_for_idx(idx, t, teacher_unav, split_week)
        prev_slot = assigned.get(f"{uc}_1", (0,"",""))[0] if idx == 2 else None
        count = 0
        for s in base:
            if prev_slot is not None and not (s > prev_slot):  # força UC_1 < UC_2
                continue
            if s in class_busy[c]:   continue
            if s in teacher_busy[t]: continue
            count += 1
        return count

    if heuristic == "degree":
        return sorted(vars_order, key=lambda v: (-deg_score[v], v))
    elif heuristic in ("mrv", "mrv-degree"):
        mrv_pairs = [(legal_count(v), v) for v in vars_order]
        mrv_sorted = sorted(mrv_pairs, key=lambda x: (x[0], x[1]))
        if heuristic == "mrv":
            return [v for _, v in mrv_sorted]
        # desempate por degree decrescente
        # grupos por legal_count, ordena dentro por -degree
        from itertools import groupby
        result = []
        for k, grp in groupby(mrv_sorted, key=lambda x: x[0]):
            bucket = [v for _, v in grp]
            bucket.sort(key=lambda v: (-deg_score[v], v))
            result.extend(bucket)
        return result
    else:
        return vars_order

# Colocação greedy 
def first_fit_schedule(data: Dict,
                       split_week: bool=False,
                       shuffle: bool=False,
                       heuristic: str="none",
                       rng: Optional[random.Random]=None) -> Optional[Dict[str, Tuple[int,str,str]]]:
    
    # Estratégia base: percorre as variáveis e coloca no 1.º slot livre
    # que não colida com docente/turma, respeitando UC_1 < UC_2.
    # Melhorias opcionais:
    #   - shuffle: baralha ordem base
    #   - heuristic: reordena dinamicamente por mrv/degree (cada passo)
    # Retorna:
    #   dict var->(slot, room, mode) ou None se falhar.

    uc_to_teacher = data["uc_to_teacher"]
    uc_to_class   = data["uc_to_class"]
    teacher_unav  = data["teacher_unavail"]
    uc_online_idx = data["uc_online_idx"]
    uc_room_req   = data["uc_room_required"]  # apenas para imprimir/labels

    rng = rng or random.Random(0xC0FFEE)

    # Ordem base de variáveis (determinista)
    pending: List[str] = build_var_list(data)
    if shuffle:
        rng.shuffle(pending)

    # Ocupações incrementais
    class_busy   = defaultdict(set)  # slots ocupados por turma
    teacher_busy = defaultdict(set)  # slots ocupados por docente
    assigned: Dict[str, Tuple[int,str,str]] = {}

    while pending:
        # Reordena dinamicamente conforme heuristic (se aplicável)
        pending = order_variables(pending, data, split_week, heuristic, class_busy, teacher_busy, assigned)

        var = pending[0]
        uc, idx_s = var.split("_"); idx = int(idx_s)
        teacher = uc_to_teacher[uc]
        turma   = uc_to_class[uc]
        is_online = idx in uc_online_idx.get(uc, set())
        room = f"Online::{uc}" if is_online else (uc_room_req.get(uc, "SalaA"))
        mode = "online" if is_online else "presencial"

        prev_slot = assigned.get(f"{uc}_1", (0,"",""))[0] if idx == 2 else None

        placed = False
        for s in candidate_slots_for_idx(idx, teacher, teacher_unav, split_week):
            if prev_slot is not None and not (s > prev_slot):
                continue
            if s in class_busy[turma]:   continue
            if s in teacher_busy[teacher]: continue
            # Coloca
            assigned[var] = (s, room, mode)
            class_busy[turma].add(s)
            teacher_busy[teacher].add(s)
            placed = True
            break

        if not placed:
            return None  # falhou com esta ordem/estado

        # Remove a variável colocada
        pending.pop(0)

    return assigned

# Exportação 
def uc_to_rgb(uc: str):
    # Cor estável por UC (hash -> HSV -> RGB).
    h = int(hashlib.md5(uc.encode("utf-8")).hexdigest(), 16)
    hue = (h % 360) / 360.0
    sat, val = 0.45, 0.95
    return colorsys.hsv_to_rgb(hue, sat, val)

def luminance(rgb):
    r, g, b = rgb
    return 0.2126*r + 0.7152*g + 0.0722*b

def text_color_for_bg(rgb):
    return "black" if luminance(rgb) > 0.6 else "white"

def frames_by_class(sol: Dict[str, Tuple[int,str,str]], data: Dict) -> Dict[str, pd.DataFrame]:
    
    # Constrói um DataFrame por turma com grelha (dias x blocos), contendo rótulos das aulas.

    frames = {}
    uc_to_class = data["uc_to_class"]
    by_class = defaultdict(list)
    for var in sol.keys():
        uc = var.split("_")[0]
        by_class[uc_to_class[uc]].append(var)

    for turma, tvars in by_class.items():
        grid = {blk: {day: "" for day in DAYS} for blk in BLOCK_LABELS}
        for var in tvars:
            uc = var.split("_")[0]
            slot, room, mode = sol[var]
            day, blk = slot_to_day_and_block(slot)
            label = f"{uc} @{'ONLINE' if mode=='online' else room}{' (online)' if mode=='online' else ''}"
            grid[blk][day] = (grid[blk][day] + " | " if grid[blk][day] else "") + label
        df = pd.DataFrame({blk: [grid[blk][d] for d in DAYS] for blk in BLOCK_LABELS}, index=DAYS)
        frames[turma] = df
    return frames

def export_csv(frames: Dict[str, pd.DataFrame], out_dir="export/csv"):

    # Exporta um CSV por turma + um CSV agregado com todas as linhas.

    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for turma, df in frames.items():
        df.to_csv(os.path.join(out_dir, f"horario_{turma}.csv"), encoding="utf-8")
        for day in df.index:
            for blk in df.columns:
                rows.append((turma, day, blk, BLOCK_TO_TIME_STR[blk], df.loc[day, blk]))
    pd.DataFrame(rows, columns=["turma","dia","bloco","hora","aula"])\
      .to_csv(os.path.join(out_dir, "horarios_todos.csv"), index=False, encoding="utf-8")

def render_table_png_pdf(df: pd.DataFrame, title: str, out_png: str, out_pdf: str):
    
    # Renderiza uma tabela (PNG/PDF) com cores por UC e hatch para online.

    fig, ax = plt.subplots(figsize=(12, 6.2), dpi=160)
    ax.axis("off")
    tbl = ax.table(cellText=df.values,
                   rowLabels=[d for d in df.index],
                   colLabels=[f"{c}\n{BLOCK_TO_TIME_STR[c]}" for c in df.columns],
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1.1, 1.6)
    ax.set_title(title, fontsize=16, fontweight="bold", pad=8)
    # Destaque cabeçalhos
    for (i,j), cell in tbl.get_celld().items():
        if i==0 or j==-1:
            cell.set_text_props(fontweight='bold'); cell.set_facecolor((0.92,0.92,0.95))
    # Coloração por UC & hatch online
    for ridx in range(df.shape[0]):
        for cidx in range(df.shape[1]):
            cell = tbl[ridx+1, cidx]; txt = df.iat[ridx, cidx]
            if not txt:
                cell.set_facecolor((1,1,1))
                continue
            parts = [p.strip() for p in txt.split("|")]
            if len(parts)==1:
                uc = parts[0].split()[0]; bg = uc_to_rgb(uc)
                cell.set_facecolor(bg)
                if "(online)" in parts[0].lower() or "@ONLINE" in parts[0]:
                    cell.set_hatch("///")
                cell.get_text().set_color(text_color_for_bg(bg))
            else:
                cell.set_facecolor((0.85,0.85,0.85)); cell.get_text().set_color("black")
                if any("(online)" in p.lower() or "@ONLINE" in p for p in parts):
                    cell.set_hatch("///")
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)

def export_png_pdf(frames: Dict[str, pd.DataFrame], out_img="export/img", out_pdf="export/pdf"):
    
    # Exporta um PNG e um PDF por turma.
    
    os.makedirs(out_img, exist_ok=True); os.makedirs(out_pdf, exist_ok=True)
    for turma, df in frames.items():
        render_table_png_pdf(df, f"Horário — {turma}",
                             os.path.join(out_img, f"horario_{turma}.png"),
                             os.path.join(out_pdf, f"horario_{turma}.pdf"))

# Main 
def main():
    ap = argparse.ArgumentParser(description="Horários — Construtor determinista (1.ª solução)")
    ap.add_argument("--data", default="ClassTT_01_tiny.txt",
                    help="Caminho para o dataset (default: ClassTT_01_tiny.txt)")
    ap.add_argument("--split-week", action="store_true",
                    help="UC_1 em 1..metade; UC_2 em metade+1..fim")
    # Melhorias opcionais (não alteram o default determinista)
    ap.add_argument("--shuffle", action="store_true",
                    help="Baralha a ordem base das variáveis (bom com --restarts)")
    ap.add_argument("--restarts", type=int, default=1,
                    help="Número de tentativas (default: 1)")
    ap.add_argument("--seed", type=int, default=12345,
                    help="Seed para o aleatório quando se usa --shuffle (default: 12345)")
    ap.add_argument("--heuristic", choices=["none","mrv","degree","mrv-degree"], default="none",
                    help="Heurística de ordenação dinâmica das variáveis (default: none)")
    args = ap.parse_args()

    # Carregar dataset
    try:
        data = load_dataset(args.data)
    except FileNotFoundError:
        print(f"[ERRO] Não encontrei '{args.data}'."); return

    rng = random.Random(args.seed)

    # Executa 1..N tentativas
    best_sol = None
    for attempt in range(1, max(1, args.restarts) + 1):
        sol = first_fit_schedule(data,
                                 split_week=args.split_week,
                                 shuffle=args.shuffle,
                                 heuristic=args.heuristic,
                                 rng=rng)
        if sol:
            best_sol = sol
            print(f"[OK] Solução encontrada no attempt {attempt}.")
            break
        else:
            print(f"[INFO] Attempt {attempt}: sem solução com as opções atuais.")

    if not best_sol:
        print("Não foi possível construir uma solução.")
        print("Sugestões: usar --split-week, --shuffle, --restarts > 1, ou heuristic mrv/mrv-degree.")
        return

    # Mostrar solução no stdout (ordenada por UC e índice)
    def key_var(v): uc, idx = v.split("_"); return (uc, int(idx))
    for var in sorted(best_sol.keys(), key=key_var):
        s,r,m = best_sol[var]
        d,b = slot_to_day_and_block(s)
        print(f"{var:>7} -> slot={s:>2} day={d} block={b} room={r} mode={m}")

    # Exportar CSV/PNG/PDF
    frames = frames_by_class(best_sol, data)
    export_csv(frames, out_dir="export/csv")
    export_png_pdf(frames, out_img="export/img", out_pdf="export/pdf")
    print("Exportações em export/csv, export/img e export/pdf.")

if __name__ == "__main__":
    main()
