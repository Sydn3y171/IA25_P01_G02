# IA25_P01_G02 — Agente CSP para Horários (IPCA)

> Trabalho prático de Inteligência Artificial: geração automática de horários de aulas com **Constraint Satisfaction Problem (CSP)**.

![banner](docs/banner.png)

## Objetivo

Criar um agente capaz de construir horários semanais válidos para várias turmas, respeitando:
- **Restrições duras (hard)**: indisponibilidades de docentes, colisões de turma/docente, salas, número máximo de aulas por dia, etc.
- **Restrições suaves (soft)**: preferência por dias distintos na mesma UC, aulas consecutivas, limitar nº de dias ativos, etc.

> Estrutura e expectativas alinhadas com o guia da UC (private repo, submissão, documentação no notebook, etc.).

---

## Restrições do Problema

**Hard**
- Aulas com duração fixa (2h/bloco) e 4 blocos por dia (B1..B4).
- Cada UC tem 2 aulas/semana.
- Um docente não pode lecionar duas aulas no mesmo slot.
- Uma turma não pode ter duas aulas no mesmo slot.
- **Máx. 3 aulas por dia por turma.**
- Indisponibilidades por docente (slots bloqueados).
- Algumas UCs exigem **sala específica** (ex.: Lab01).
- Aulas **online** (quando existirem para a UC/índice) não ocupam sala física.

**Soft**
- Aulas da mesma UC em **dias distintos** (preferência).
- **Aulas consecutivas** no mesmo dia (por turma).
- Limitar a **4 dias ativos** por turma (preferência).

---

## Tecnologias

- **Python 3.10+**
- [python-constraint](https://pypi.org/project/python-constraint/) — modelação/solução CSP
- **pandas** — grelhas e exportação CSV
- **matplotlib** — exportação **PNG/PDF** com **cores por UC**

---

## Instalação

### 1) Criar ambiente virtual

**Windows (PowerShell)**
```powershell
pip install virtualenv
virtualenv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux (bash/zsh)**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Dependências
```bash
pip install python-constraint pandas matplotlib
```

---

## Como correr

Coloca o dataset `ClassTT_01_tiny.txt` ao lado do `main.py` e executa:

**macOS/Linux**
```bash
python3 -u main.py
```

**Windows**
```powershell
python main.py
```

O programa:
1) Valida o dataset e mostra **diagnóstico** (domínios, capacidades).  
2) Procura a **1.ª solução viável** por camadas (mais permissivo → completo).  
3) Imprime horários por **turma** e por **docente**.  
4) Exporta resultados para **CSV**, **PNG** e **PDF** com **cores por UC**.

---

## Estrutura dos outputs

Após correr, encontras:

```
export/
  csv/
    horario_t01.csv
    horario_t02.csv
    horario_t03.csv
    horarios_todos.csv     # (agregado)
  img/
    horario_t01.png
    horario_t02.png
    horario_t03.png
  pdf/
    horario_t01.pdf
    horario_t02.pdf
    horario_t03.pdf
```

- **PNG/PDF** usam **cor consistente por UC** e padrão *hatch* “///” para aulas **ONLINE**.
- **CSV** agregado inclui colunas: `turma, dia, bloco, hora, aula`.

---

## Como funciona

- **Variáveis**: para cada UC existem duas variáveis `UC_1` e `UC_2`.  
- **Domínios**: pares `(slot, sala, modo)` onde:
  - `slot ∈ {1..20}` (5 dias × 4 blocos), filtrado por indisponibilidades do docente.
  - `sala` é a obrigatória (se existir) ou uma sala base (`SalaA`, `SalaB`) para presenciais; **ONLINE** marca modo virtual.
  - `modo` ∈ {`presencial`, `online`}.
- **Restrições**:
  - Unicidade `slot+sala` nas aulas presenciais (evita colisões de sala).
  - Sem sobreposição por **docente** e por **turma**.
  - **Máx. 3 aulas/dia** por turma (hard).
  - Se ambas as aulas de uma UC forem **online**, ficam **no mesmo dia** (hard de desafio).
  - **Quebra de simetria**: `UC_1` antes de `UC_2` (reduz espaço de procura).
- **Procura**:
  - **MinConflictsSolver** (heurístico local) com *restarts* até um **deadline** por camada.
  - Camadas progressivas (debug → teste → completo) para garantir a 1.ª solução rápida.
- **Score (indicativo)**:
  - + dias distintos na mesma UC; + consecutivas no mesmo dia; − >4 dias ativos; − excesso ao *max3* quando tratado como soft.

---

## Dataset (exemplo mínimo)

```
#cc — classes → UCs
t01         UC11 UC12 UC13 UC14 UC15
t02         UC21 UC22 UC23 UC24 UC25
t03         UC31 UC32 UC33 UC34 UC35

#dsd — docentes → UCs
jo          UC11 UC21 UC22 UC31
mike        UC12 UC23 UC32
rob         UC13 UC14 UC24 UC33
sue         UC15 UC25 UC34 UC35

#tr — indisponibilidades (docente, slots)
mike        13 14 15 16 17 18 19 20
rob         1  2  3  4
sue         9  10 11 12 17 18 19 20

#rr — sala obrigatória (UC, sala)
UC14        Lab01
UC22        Lab01

#oc — aulas online (UC, indice)
UC21        2
UC31        2
```

> Nota: cada linha de `#oc` **tem exatamente 2 tokens**.

---

## Troubleshooting

- **“Variáveis com domínio ZERO”**  
  → há UC com docente sem slots livres ou sala impossível. Revê `#tr` e `#rr`.

- **Demora a encontrar solução**  
  → confirma que o dataset está limpo (sem comentários extra em `#oc`), aumenta `TOTAL_SECONDS` em `main.py` e deixa as **camadas** como estão (o *debug/teste* costuma achar rapidamente).

- **Imagens/PDF sem cores**  
  → garante `matplotlib` atualizado; corre sem temas externos; não feches as figuras antes do `savefig`.

---

## Organização sugerida do repo

```
.
├─ main.py                 # agente + exportadores
├─ ClassTT_01_tiny.txt     # dataset
├─ README.md               # este ficheiro
├─ docs/
│   └─ banner.png          # imagem para o topo
└─ export/                 # gerado pelo programa
```

---

## Autores

- António Ferreira 9657
- Mafalda Barão 20446  
- Gonçalo Gomes 23039
- Rúben Dias 23033
- João Morais 23041

---

## Comandos rápidos

```bash
# 1) Ambiente
python3 -m venv .venv
source .venv/bin/activate           # Windows: .\.venv\Scripts\Activate.ps1

# 2) Dependências
pip install python-constraint pandas matplotlib

# 3) Executar
python3 -u main.py

# 4) Ver resultados
open export/img/horario_t01.png     # macOS
# ou abre export/ em qualquer SO
```
