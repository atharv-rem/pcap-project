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
s.append(P("Running 400 rainstorms over a real map of Bengaluru to find the places that "
           "flood most often, with the work shared across many processes",
           subtitle))
s.append(Spacer(1, 6))
s.append(HRFlowable(width="100%", thickness=0.6, color=LINE, spaceAfter=10))
s += table([
    ["Course", "Parallel Computing (PCAP) - Project Synopsis"],
    ["Programme", "B.Tech, Computer Science and Engineering"],
    ["Made by", "Atharv Remeshan - 245805386<br/>Pranshu Thakkar - 245805158<br/>"
              "Ritwik Gupta - 245805240"],
    ["Tools", "C with OpenMPI; Python (NumPy, Matplotlib) for the maps and charts; "
              "raylib for the live demo"],
], [0.25, 0.75], header=False)

s.append(P("1. Summary", h1))
s.append(P("Bengaluru floods almost every monsoon. Roads like the Outer Ring Road and junctions "
           "like Silk Board turn into small lakes. Rain water always runs downhill and collects "
           "in low places, so the shape of the land already tells us a lot about where water "
           "will go."))
s.append(P("We took a real height map of Bengaluru from satellite data and let 400 different "
           "rainstorms fall on it, from short light showers to long heavy downpours. A simple "
           "computer model moves the rain water downhill, step by step. For every small patch "
           "of land, we record how deep the water gets. The result is a colour-coded flood map "
           "of the city, a list of the most flood-prone areas, and a check against the places "
           "the city corporation (BBMP) has officially listed as flood-prone."))
s.append(P("The goal of the project is to learn parallel programming. The 400 storms do not "
           "depend on each other, so many processes can work on different storms at the same "
           "time. We wrote all the code that shares out the work and collects the results "
           "ourselves, using MPI. The map shows where flooding is likely; it is not a weather "
           "forecast."))

s.append(P("2. What the program does", h1))
s += table([
    ["Step", "In plain words"],
    ["1. Load the map", "Read the ground height of every patch of land. The map has "
     "1.33 million patches, each 30 m x 30 m, covering about 1,200 km<super>2</super> of "
     "Bengaluru. We use FABDEM satellite data (buildings and trees removed) and also cut "
     "about 990 km of known drains into it"],
    ["2. Make the storms", "Create 400 storms: 20 rain strengths (10 to 60 mm per hour) times "
     "20 lengths (1 to 4 hours)"],
    ["3. Run each storm", "Rain falls everywhere. Every 30 seconds of storm time, water moves "
     "from each wet patch to its lower neighbours. After the rain stops, we let the water "
     "drain for 2 more hours"],
    ["4. Combine the storms", "For every patch, count how often it flooded and remember the "
     "deepest water it ever had"],
    ["5. Show the results", "Draw the flood map, rank 500 m areas by risk, compare with 386 "
     "official BBMP flood spots, and make a table of flooded area per storm"],
], [0.25, 0.75], cap="Table 1: The five steps of the program.")

s.append(P("3. Why we use parallel processing", h1))
s.append(bullets([
    "<b>There is a lot of work.</b> 400 storms, each with up to 720 time steps, on 1.33 million "
    "patches: billions of small calculations. One storm takes about 4 to 14 seconds on one "
    "processor core, so all 400 take about an hour on one process.",
    "<b>The work splits easily.</b> Each storm is completely separate from the others. Every "
    "process gets its own copy of the map and runs whole storms by itself. The processes only "
    "need to talk at the start (to get the settings) and at the end (to add up the results).",
    "<b>But storms are not the same size.</b> A 4-hour storm takes about twice as long as a "
    "1-hour storm. If we simply give each process an equal number of storms, some finish early "
    "and sit idle while others are still busy. Sharing the work fairly is the interesting "
    "problem in this project.",
    "<b>Some parts cannot be sped up.</b> Adding up the results at the end, loading the map and "
    "drawing the pictures take the same time however many processes we use.",
]))

s.append(P("4. How the processes work together", h1))
s.append(P("4.1 Sharing the settings", h2))
s.append(P("Process 0 reads the settings (which map, which storms) and sends them to all other "
           "processes. Each process then loads the map from disk by itself, so the big map is "
           "never sent between processes. Only storm numbers are sent."))
s.append(P("4.2 Handing out storms one at a time (dynamic mode)", h2))
s.append(P("Process 0 acts as a manager and does not run storms itself. Each worker tells the "
           "manager \"I am ready\" (and sends the result of its last storm), and the manager "
           "replies with the next storm number, or \"stop\" when none are left. A worker that "
           "gets a short storm simply comes back sooner, so nobody waits."))
s.append(P("4.3 Fixed shares (static mode, for comparison)", h2))
s.append(P("Each worker gets a fixed list of storms at the start and never talks to the manager. "
           "This is simpler, but it cannot adjust when some storms take longer than others."))
s.append(P("4.4 Collecting the results", h2))
s.append(P("At the end, the flood counts from all workers are added together, patch by patch, "
           "and the deepest water is kept. We also collect how long each worker was busy, so we "
           "can see how evenly the work was shared."))
s.append(P("4.5 Checking the answer", h2))
s.append(P("The model has no randomness, so the parallel version must give exactly the same "
           "answer as the one-process version. We compare the output files byte by byte."))
s.append(P("4.6 Live demo", h2))
s.append(P("A separate window shows one storm happening on a street map of Bengaluru. You can "
           "watch the water spread, zoom in, and point at any spot to see its height and water "
           "depth."))

mpi = table([
    ["MPI feature", "What we use it for"],
    ["Broadcast", "Process 0 sends the same settings to every process"],
    ["Send and receive", "Workers ask for the next storm and the manager answers whoever "
     "asks first"],
    ["Reduce", "Adds up the flood counts from all processes (sum) and keeps the deepest water "
     "(maximum)"],
    ["Gather", "Collects how long each process was busy"],
    ["Barrier", "Makes all processes start and stop the clock together"],
    ["Timer", "Measures how long the run takes"],
], [0.25, 0.75], cap="Table 2: The MPI features we use.")
s.append(KeepTogether([P("5. MPI features used", h1)] + mpi))

s.append(P("6. What we found", h1))
s.append(P("6.1 The parallel answer is exactly right", h2))
s.append(P("With 2 and 4 processes, in both modes, the output files are exactly the same as "
           "with one process, down to the last byte. The model also loses almost no water "
           "(less than 0.0003% error)."))

s.append(P("6.2 Speed", h2))
s.append(P("We timed 400 storms on a smaller 90 m version of the map, three times each, and "
           "used the middle value. \"Speed-up\" means how many times faster than one process. "
           "\"Imbalance\" means how much more work the busiest worker did than the average "
           "worker (1.00 = perfectly fair)."))
s += table([
    ["Processes", "Dynamic", "Static", "Speed-up (dynamic / static)",
     "Imbalance (dynamic / static)"],
    ["1", "402 s", "-", "1.0x", "-"],
    ["4", "246 s", "253 s", "1.6x / 1.6x", "1.00 / 1.04"],
    ["8", "170 s", "178 s", "2.4x / 2.3x", "1.01 / 1.05"],
    ["14", "131 s", "138 s", "<b>3.1x / 2.9x</b>", "<b>1.02 / 1.10</b>"],
], [0.14, 0.14, 0.14, 0.29, 0.29], cap="Table 3: Speed-up and imbalance.")
s.append(bullets([
    "<b>Dynamic mode shares the work more fairly.</b> Its busiest worker does only 2% more "
    "than average; with fixed shares it is 8 to 10%. Dynamic was also a little faster (about "
    "5%), but a second test showed that timings on this laptop change by 10 to 20% from run "
    "to run, so the fairness numbers are the clearer result.",
    "<b>Why only about 3 times faster with 14 processes?</b> Because of the laptop, not MPI. "
    "One storm takes 1.0 s when it runs alone, but 4.1 s when 13 storms run at once. All "
    "processes share the same memory, cache and power, and some of the CPU cores are slower "
    "\"efficiency\" cores. The MPI messages themselves are tiny.",
    "The full 400-storm run on the detailed 30 m map takes about 14 minutes with 12 processes, "
    "instead of about an hour with one.",
]))
s.append(KeepTogether([
    Table([[figure(os.path.join(ROOT, "results/bench/figures/speedup.png"), 80),
            figure(os.path.join(ROOT, "results/bench/figures/per_storm.png"), 80)]],
          colWidths=[W / 2, W / 2]),
    P("Figure 1: Left, how much faster the program gets (the dashed line is the perfect case). "
      "Right, each storm gets slower as more processes share the laptop.", caption)]))

s.append(P("6.3 Where Bengaluru floods", h2))
s.append(bullets([
    "Flooding follows the city's natural low lines: valleys, drains and chains of lakes. "
    "Hot spots are in the west and centre (Vijayanagar, Malleshwaram, Rajajinagar) and around "
    "the south-east lakes (Bellandur, Outer Ring Road).",
    "Stronger rain floods much more land: 13.5 km<super>2</super> for the lightest storm "
    "(10 mm/h for 1 hour), 58 km<super>2</super> for 60 mm/h for 1 hour, and "
    "191 km<super>2</super> for the heaviest (60 mm/h for 4 hours). How hard it rains matters "
    "more than how long.",
    "<b>87 of the 384 official BBMP flood spots fall in our riskiest 10% of areas. That is "
    "2.3 times more than random places would.</b> 6 of our 10 riskiest areas have a BBMP "
    "flood spot within 1 km.",
]))
s.append(KeepTogether([
    figure(os.path.join(ROOT, "results/full_fabdem_drains/peak_depth_map.png"), 118),
    P("Figure 2: The deepest water each place reached in any of the 400 storms, on a street "
      "map. Black dots: BBMP flood spots. Grey: lakes.", caption)]))

s.append(P("6.4 Making the map more accurate", h2))
s.append(P("We tested each improvement fairly: we chose settings using half of the BBMP spots "
           "and measured the result on the other half. The score below is the chance that a "
           "real flood spot is rated riskier than a random place (0.5 = guessing, "
           "1.0 = perfect)."))
s += table([
    ["Version of the model", "Score on the unseen half"],
    ["Original height map (SRTM, includes rooftops and trees)", "0.55"],
    ["Better height map (FABDEM, buildings and trees removed)", "0.68"],
    ["+ about 990 km of known drains added", "0.71"],
    ["+ judging risk by the deepest water during the storm", "0.71"],
], [0.7, 0.3], cap="Table 4: Each improvement and its score.")
s.append(P("We also tried letting rain soak into the ground and using a wider range of storms. "
           "Neither made the map more accurate."))

s.append(P("6.5 Limits", h2))
s.append(P("This map shows where flooding is likely; it is not a forecast. The model does not "
           "know about blocked or small drains, soil, buildings or underpasses. So about 7 out "
           "of 10 real flood spots still fall outside our riskiest areas, and the water depths "
           "are model numbers, not exact predictions."))

tools = table([
    ["Language", "C, built with the MPI compiler (mpicc)"],
    ["MPI library", "OpenMPI 4.1"],
    ["Height map", "FABDEM (30 m, buildings and trees removed, University of Bristol); SRTM "
     "for comparison"],
    ["Flood spots", "386 official BBMP flood locations (open data from OpenCity)"],
    ["Map data", "OpenStreetMap: drains, lakes and the street map, (c) OpenStreetMap "
     "contributors"],
    ["Live demo", "raylib, a small C graphics library"],
    ["Computer", "14-core laptop (Intel Core Ultra 5 125H), Ubuntu 24.04 under WSL; tested "
     "with up to 14 processes"],
    ["Charts", "Python with NumPy and Matplotlib"],
], [0.25, 0.75], header=False)
s.append(KeepTogether([P("7. Tools", h1)] + tools))

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                        topMargin=20 * mm, bottomMargin=22 * mm,
                        title="Bengaluru Flood-Risk Map using MPI - Project Synopsis",
                        author="Atharv Remeshan, Pranshu Thakkar, Ritwik Gupta")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
