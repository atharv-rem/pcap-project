"""Build the project synopsis PDF in the style of the course template."""
import os
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, KeepTogether, ListFlowable, ListItem,
                                Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

OUT = sys.argv[1]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root
GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#bbbbbb")
HEAD_BG = colors.HexColor("#eeeeee")

title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=25,
                       alignment=TA_CENTER, spaceAfter=6)
subtitle = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11.5, leading=15,
                          alignment=TA_CENTER, textColor=GREY)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13.5, leading=17,
                    spaceBefore=10, spaceAfter=5, keepWithNext=1)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14,
                    spaceBefore=6, spaceAfter=3, keepWithNext=1)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.2,
                      alignment=TA_JUSTIFY, spaceAfter=6)
cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=9.3, leading=12)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
caption = ParagraphStyle("caption", fontName="Helvetica", fontSize=8.5, leading=11,
                         alignment=TA_CENTER, textColor=GREY, spaceBefore=3, spaceAfter=8)

W = A4[0] - 2 * 22 * mm


def P(text, style=body):
    return Paragraph(text, style)


def table(rows, widths, header=True, cap=None):
    data = [[P(c, cellb if (header and i == 0) else cell) for c in r]
            for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * W for w in widths])
    style = [("GRID", (0, 0), (-1, -1), 0.5, LINE),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
    t.setStyle(TableStyle(style))
    out = [t]
    if cap:
        out.append(P(cap, caption))
    return out


def figure(path, width_mm):
    """Image scaled to width_mm, keeping its aspect ratio."""
    img = Image(path)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


def bullets(items):
    return ListFlowable(
        [ListItem(P(t), leftIndent=14, value="square") for t in items],
        bulletType="bullet", start="square", bulletFontSize=6, leftIndent=14,
        bulletOffsetY=-2)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(GREY)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


s = []
s.append(P("Bengaluru Flood-Risk Map using MPI", title))
s.append(P("Running hundreds of rainstorms over the real terrain of Bengaluru to find the "
           "places that flood most often, with the storms shared across many processes",
           subtitle))
s.append(Spacer(1, 6))
s.append(HRFlowable(width="100%", thickness=0.6, color=LINE, spaceAfter=10))
s += table([
    ["Course", "Parallel Computing (PCAP) - Project Synopsis"],
    ["Programme", "B.Tech, Computer Science and Engineering"],
    ["Made by", "Ritwik - 245805240<br/>Atharv - 245805386<br/>Pranshu - 245805158"],
    ["Tools", "C with OpenMPI; Python (NumPy, Matplotlib) for the maps and charts; "
              "raylib for the live demo"],
], [0.25, 0.75], header=False)

s.append(P("1. Summary", h1))
s.append(P("Bengaluru floods badly in heavy rain: roads such as the Outer Ring Road and junctions "
           "such as Silk Board turn into lakes almost every monsoon. Water runs downhill and "
           "collects in low ground, so the shape of the land alone already says a lot about "
           "where the water will go."))
s.append(P("This project takes a real elevation map of Bengaluru from satellite data and "
           "lets hundreds of different storms fall on it, from short light showers to long "
           "heavy downpours. A deliberately simple water model moves the rain downhill, step "
           "by step. For every patch of ground the program counts in how many of the storms "
           "it ends up under water. The result is a colour-coded flood-risk map of the city, "
           "a ranked list of the most flood-prone areas, and a check against the places the "
           "city corporation (BBMP) has officially listed as flood-prone."))
s.append(P("The aim is to learn parallel programming, not hydrology. The storms do not depend "
           "on each other, so they can be shared out among many processes. Everything to do "
           "with dividing the work, passing messages between processes and combining the "
           "results is written by us with MPI. The map is a screening map, not a forecast."))

s.append(P("2. What the program has to do", h1))
s += table([
    ["Step", "In plain words"],
    ["1. Load the terrain", "Read the height of the ground for every cell of the map: "
     "1,116 x 1,188 cells of about 30 m, covering about 1,200 km<super>2</super> of "
     "Bengaluru (FABDEM satellite data, with buildings and trees removed); about 990 km of "
     "mapped drains and streams are cut into it"],
    ["2. Make the storm list", "Build 400 storms: 20 rain intensities (10 to 60 mm per hour) "
     "times 20 durations (1 to 4 hours)"],
    ["3. Run each storm", "Rain falls on every cell; every 30 simulated seconds each wet cell "
     "passes some of its water to its lower neighbours; after the rain stops the water drains "
     "for 2 more hours. A cell counts as flooded if it is still more than 0.3 m deep"],
    ["4. Combine the storms", "For every cell, count in how many storms it flooded and "
     "remember the deepest water it ever had"],
    ["5. Report", "Draw the flood-risk map, rank 500 m areas by risk, compare the ranking "
     "with 386 official BBMP flood points, and tabulate the flooded area per storm"],
], [0.25, 0.75], cap="Table 1: The five steps of the flood-risk program.")

s.append(P("3. Where the parallel work is", h1))
s.append(P("Not every step splits equally well, and that is what makes this project worth "
           "studying."))
s.append(bullets([
    "<b>Step 3 is almost all of the time, and it splits perfectly by storm.</b> One storm on "
    "the 30 m map takes between about 4 and 14 seconds on one core, so 400 storms take about "
    "an hour on one process. The storms are completely independent: every process keeps its own copy of "
    "the map and runs whole storms without talking to anyone.",
    "<b>But the storms are not equal.</b> A 4-hour storm needs twice as many time steps as a "
    "1-hour storm, and a wet map takes longer to compute than a dry one. If each process is "
    "simply given a fixed share of the storm list, some finish long before others and sit "
    "idle.",
    "<b>Step 4 is a combining step.</b> The flood counts from all processes must be added "
    "together cell by cell, and the deepest water kept. This happens once at the end, and its "
    "cost does not shrink when more processes are added.",
    "<b>Steps 1, 2 and 5 are small</b> and run on one process (step 5 in Python, after the "
    "run).",
]))
s.append(P("The limits worth reporting are the uneven storm lengths, the final combining step, "
           "and the fact that the processes share one laptop's memory and cores, so each "
           "extra process helps a little less than the one before."))

s.append(P("4. How the processes work together", h1))
s.append(P("4.1 Sharing the settings", h2))
s.append(P("The first process reads the command line (the map file, the rain ranges, the "
           "flood depth) and broadcasts the settings to every other process. Each process then "
           "loads the map from disk and builds the storm list itself, so no map data ever has "
           "to be sent between processes. Only storm numbers travel."))
s.append(P("4.2 Handing out storms on demand (dynamic mode)", h2))
s.append(P("The first process becomes a coordinator that only hands out work and does not "
           "simulate. Each worker sends a \"ready\" message that also carries the result of "
           "its last storm, and gets back the number of the next storm, or a stop signal when "
           "none are left. A worker that drew a short storm simply comes back sooner, so "
           "everyone stays busy."))
s.append(P("4.3 Fixed shares (static mode, for comparison)", h2))
s.append(P("Each worker is given one fixed, contiguous block of the storm list up front and "
           "runs it without any messages. This is simpler but cannot react to storms taking "
           "different times. Running both modes on the same storms shows how much the "
           "on-demand version gains."))
s.append(P("4.4 Bringing the results together", h2))
s.append(P("At the end, the flood counts of all processes are added together and the deepest "
           "water is combined, cell by cell, at the first process. The busy time of every "
           "process is gathered too, so the program can report how evenly the work was "
           "shared. The first process then writes the result files."))
s.append(P("4.5 Checking that the answer is right", h2))
s.append(P("The water model has no randomness, so the parallel program must give exactly the "
           "same answer as a plain one-process version. The output files of both are compared "
           "byte for byte for every mode and number of processes."))
s.append(P("4.6 Showing it live", h2))
s.append(P("A separate window (raylib) replays one storm step by step on an OpenStreetMap "
           "street map, so the audience can watch the water spread, zoom into an area, and read "
           "the height and water depth of any point."))

mpi = table([
    ["MPI feature", "What it does, in plain words"],
    ["Broadcast", "The first process sends the same settings (map file, rain ranges) to "
     "everybody"],
    ["Send and receive", "Workers ask for the next storm and the coordinator answers; "
     "\"receive from anyone\" lets it serve whichever worker is ready first"],
    ["Reduce", "Adds up the flood counts of all processes cell by cell (sum), and keeps the "
     "deepest water seen (maximum)"],
    ["Gather", "Collects every process's busy time, and in static mode the per-storm results, "
     "at the first process"],
    ["Barrier", "Makes all processes start and stop the clock together"],
    ["Timer", "Measures the total run time and each process's busy time"],
], [0.25, 0.75], cap="Table 2: The MPI ideas the project covers.")
s.append(KeepTogether([P("5. MPI features used", h1)] + mpi))

s.append(P("6. What we found", h1))
s.append(P("6.1 The parallel answer is exactly right", h2))
s.append(P("Dynamic and static mode on 2 and 4 processes produce result files that are "
           "byte-for-byte identical to the one-process program (checked with <i>cmp</i>, and "
           "re-checked after every change to the model). Water is conserved to within 0.0003%."))

s.append(P("6.2 Speed", h2))
s.append(P("Benchmark on the 90 m version of the map (400 storms, 3 repetitions, median wall "
           "time, laptop on mains power):"))
s += table([
    ["Processes", "Dynamic", "Static", "Speed-up (dynamic / static)",
     "Load imbalance (dynamic / static)"],
    ["1", "402 s", "-", "1.0x", "-"],
    ["4", "246 s", "253 s", "1.6x / 1.6x", "1.00 / 1.04"],
    ["8", "170 s", "178 s", "2.4x / 2.3x", "1.01 / 1.05"],
    ["14", "131 s", "138 s", "<b>3.1x / 2.9x</b>", "<b>1.02 / 1.10</b>"],
], [0.14, 0.14, 0.14, 0.29, 0.29],
    cap="Table 3: Speed-up and load imbalance (busiest worker / average worker).")
s.append(bullets([
    "<b>Handing out storms on demand balances the work.</b> Dynamic mode keeps the busiest "
    "worker within 2% of the average; fixed shares reach 8-10%. In the 3-repetition medians "
    "dynamic is also faster from 4 processes up, but only by about 5%, and a later "
    "single-repetition check (2.8x dynamic / 3.1x static at 14 processes) showed that "
    "run-to-run noise on this laptop (10-20%) is larger than that gap. The imbalance numbers "
    "are the clearer evidence.",
    "<b>The speed-up flattens because of the laptop, not MPI.</b> The same storm takes 1.0 s "
    "when it runs alone but 4.1 s when 13 run at the same time: all processes share one "
    "laptop's cache, memory bandwidth and power budget, and the CPU mixes fast and slower "
    "cores. MPI's own cost is tiny (each message is a few bytes).",
    "The full 400-storm run on the 30 m map takes about 14 minutes on 12 processes, against "
    "about an hour on one.",
]))
s.append(KeepTogether([
    Table([[figure(os.path.join(ROOT, "results/bench/figures/speedup.png"), 80),
            figure(os.path.join(ROOT, "results/bench/figures/per_storm.png"), 80)]],
          colWidths=[W / 2, W / 2]),
    P("Figure 1: Left, speed-up against the ideal line. Right, the average time per storm "
      "grows as more processes share the laptop.", caption)]))

s.append(P("6.3 Where Bengaluru floods", h2))
s.append(bullets([
    "Flood risk follows the city's natural drainage: valleys, drain lines and chains of lakes. "
    "Clusters stand out in the west and centre (Vijayanagar, Malleshwaram, Rajajinagar) and "
    "around the south-east lakes (Bellandur, Outer Ring Road).",
    "The flooded area grows strongly with rain: 13.5 km<super>2</super> for the lightest storm "
    "(10 mm/h for 1 h), 58 km<super>2</super> for 60 mm/h for 1 h and 191 km<super>2</super> "
    "for the heaviest (60 mm/h for 4 h). Intensity matters more than duration.",
    "<b>87 of 384 official BBMP flood points lie in the riskiest 10% of the map's 500 m "
    "areas: 2.3 times more often than random places would.</b> 6 of the 10 highest-ranked "
    "areas have a BBMP flood point within 1 km.",
]))
s.append(KeepTogether([
    figure(os.path.join(ROOT, "results/full_fabdem_drains/peak_depth_map.png"), 118),
    P("Figure 2: Deepest water reached in any of the 400 storms (30 m cells, mapped drains "
      "included), over an OpenStreetMap street map. Black dots: BBMP flood points; grey: lakes.",
      caption)]))

s.append(P("6.4 Making the map more accurate", h2))
s.append(P("Each improvement was tested on half of the BBMP points and scored on the other half, "
           "so the result is not tuned to the test. The score (AUC) is the chance that a real "
           "flood point is rated riskier than a random place: 0.5 means guessing, 1.0 perfect."))
s += table([
    ["Version of the model", "Score on unseen points (AUC, within 300 m)"],
    ["Original terrain (SRTM, includes rooftops and trees)", "0.55"],
    ["Better terrain (FABDEM, buildings and trees removed)", "0.68"],
    ["+ about 990 km of mapped drains cut into the terrain", "0.71"],
    ["+ risk scored by the deepest water instead of water left at the end", "0.71"],
], [0.7, 0.3], cap="Table 4: How each change improved agreement with real flood points.")
s.append(P("Soaking rain into the ground (a constant loss rate) and a wider range of storms "
           "were also tested and did not improve the agreement."))

s.append(P("6.5 Limits", h2))
s.append(P("This is a screening map, not a forecast. The model has no drain capacity or "
           "blockages, no soil, no buildings and no underpasses, so about 7 in 10 real flood "
           "points still fall outside the riskiest zone, and depths and times are model values. "
           "Timings on this laptop vary between sessions, so all speed comparisons come from one "
           "benchmark session."))

tools = table([
    ["Language", "C (C11), compiled with the MPI compiler wrapper (mpicc)"],
    ["MPI library", "OpenMPI 4.1"],
    ["Terrain data", "FABDEM V1-2 (Copernicus 30 m elevation with buildings and trees removed, University of Bristol); SRTM 30 m for comparison"],
    ["Flood points", "386 BBMP flood-vulnerable, flood-prone and low-lying locations (open "
     "data from OpenCity, source KSRSAC)"],
    ["Map data", "OpenStreetMap: drains and streams (cut into the terrain), lakes (left out "
     "of the ranking) and the street map behind the results, (c) OpenStreetMap contributors"],
    ["Live demo", "raylib, a small C graphics library"],
    ["Machine", "A 14-core laptop (Intel Core Ultra 5 125H) running Ubuntu 24.04 under WSL; "
     "tested up to 14 processes"],
    ["Graphs", "Python with NumPy and Matplotlib, for the maps and timing charts in the report"],
], [0.25, 0.75], header=False)
s.append(KeepTogether([P("7. Tools", h1)] + tools))

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                        topMargin=20 * mm, bottomMargin=22 * mm,
                        title="Bengaluru Flood-Risk Map using MPI - Project Synopsis",
                        author="Ritwik, Atharv, Pranshu")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
