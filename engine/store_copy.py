"""Product descriptions written for the product AND the platform (owner, 14 Nov: "description should be according to
the product and platform"). Every fact comes from the product itself (page counts, files, track lengths).

Platforms:
- payhip / gumroad: a buyer landing from a link: hook, what's inside, who it's for, how it works, guarantee line.
- kdp: Amazon book description: no links or prices in the text, no "download" (it's a printed book), age/benefit
  first, keywords used naturally.
- social: a 1-2 line caption for posts/Stories with the shop link added by the poster."""
from __future__ import annotations

KIND = {"money_budget_planner": "sheet", "bloop_colouring_book": "print", "brain_snack_puzzle_book": "print",
        "christmas_colouring_book": "print"}

COPY = {
    "activity_book": dict(
        hook="Hours of screen-free fun that sneak in learning: mazes, dot to dot, spot the difference and more.",
        inside=["12 mazes that grow from easy to tricky", "12 dot-to-dot pictures and 12 coloring pages",
                "8 spot-the-difference puzzles and 10 kid-sized word searches",
                "Answers for every puzzle, fun facts, star self-ratings and a certificate"],
        who="Ages 4-8: road trips, rainy days, quiet time and classrooms.",
        how="Pick any page and play. Check the answers at the back when you're done.",
        note="Big, clear pages made for little hands.",
        kdp="Hours of screen-free fun that sneak in learning! 12 mazes that grow from easy to tricky, 12 dot-to-dot "
            "pictures, 8 spot-the-difference puzzles, 10 kid-sized word searches and 12 coloring pages starring Bloop & "
            "Friends. Answers for every puzzle, fun facts, a star self-rating on every page and a certificate are "
            "included. Perfect for road trips, rainy days and quiet time, ages 4-8.",
        social="88-page kids activity book: mazes, dot to dot, spot the difference"),
    "seniors_word_search": dict(
        hook="A trip down memory lane, one easy-to-read puzzle at a time.",
        inside=["50 word searches, each on a theme from the good old days: soda fountains, drive-ins, sock hops and more",
                "Extra-large letters, one puzzle per page",
                "Words only go across, down or diagonally down: no backwards words",
                "Answers at the back"],
        who="Seniors, grandparents and anyone who loves a relaxing, nostalgic puzzle. A thoughtful gift.",
        how="Find each word, circle it and tick it off the list.",
        note="Gentle on the eyes and the mind: perfect for daily brain exercise.",
        kdp="Take a trip down memory lane with 50 large-print word search puzzles, each themed on everyday life from the "
            "good old days: the soda fountain, the drive-in, the sock hop, grandma's kitchen, school days and more. "
            "Extra-large letters, one puzzle per page, and words that only run across, down or diagonally down make it "
            "easy on the eyes. Answers are at the back. A thoughtful gift for parents and grandparents.",
        social="Large print nostalgia word search: 50 easy puzzles from the good old days"),
    "tracing_workbook": dict(
        hook="The pencil-control and letter practice preschoolers need before kindergarten, made fun.",
        inside=["6 pen-control pages: lines, zig zags, waves, hills, loops, spirals",
                "A-Z capitals and lowercase: a big letter to trace plus 4 rows on handwriting lines",
                "Numbers 0-20 with counting dots, and 8 shapes to trace and color",
                "A 'How did I do?' star rating, fun facts and cheers on every page",
                "A certificate to celebrate at the end"],
        who="Ages 3-5: preschool, pre-K and kindergarten prep, at home or in the classroom.",
        how="Start at the green dot and follow the dots. One or two pages a day is perfect.",
        note="Large, clear letters with plenty of space for little hands.",
        kdp="The tracing workbook preschoolers need before kindergarten: 6 pen-control pages (lines, zig zags, waves, "
            "loops, spirals), A-Z capitals and lowercase with a big letter to trace and four rows on handwriting lines, "
            "numbers 0-20 with counting dots, and 8 shapes to trace and color. Every page has a 'How did I do?' star "
            "rating, a fun fact or a cheer, and a certificate waits at the end. Large print, 8.5 x 11 inches, 90 pages.",
        social="90-page preschool tracing workbook: letters, numbers, shapes, pen control"),
    "color_by_number": dict(
        hook="Coloring that teaches: match the number, learn the color, reveal the picture.",
        inside=["24 color-by-number pages with Bloop, Pip, Mo, Dee, fruit, animals and treats",
                "A color key on every page (red, blue, green and more)",
                "An answer key with the finished pictures",
                "Star self-rating, fun facts and a certificate"],
        who="Ages 4-8 who love coloring and are learning numbers and color names.",
        how="Find the number, check the key, color the part. Peek at the answer key only at the end!",
        note="Big, clear shapes: no tiny spaces to frustrate little artists.",
        kdp="Coloring that teaches! 24 cheerful color-by-number pictures with Bloop & Friends, fruit, animals and treats. "
            "Every page has a color key, so kids practice numbers and color names as they reveal each picture. An "
            "answer key, fun facts, a star self-rating on every page and a certificate are included. For ages 4-8.",
        social="Color by number for kids 4-8: learn colors and numbers"),
    "planner_2027": dict(
        hook="Start 2027 with a plan you'll actually use: everything on paper, nothing to subscribe to.",
        inside=["2027 year at a glance + a goals page for 6 areas of life",
                "12 monthly calendars with the real 2027 dates and US holidays",
                "Weekly planner, daily planner (6 AM - 9 PM) and a 31-day habit tracker",
                "Monthly budget, reading list and dotted notes pages",
                "21 pages, US Letter (prints on A4 with 'fit to page'); reprint any page as often as you like"],
        who="Students, busy parents, freelancers and anyone setting New Year goals.",
        how="Download the PDF, print the whole bundle or just the pages you need, and put it in a binder.",
        note="Printer-friendly: white pages with soft color accents to save ink.",
        social="2027 Planner Bundle: monthly, weekly, daily, habits and goals in 21 printable pages"),
    "money_budget_planner": dict(
        hook="Stop wondering where your money went. This planner shows you exactly where it goes, in 5 minutes a month.",
        inside=["Budget spreadsheet that does the math: income, bills, spending and what's left",
                "Your plan side by side with the 50/30/20 rule (needs / wants / savings)",
                "Savings goals that fill up as you save",
                "Debt tracker: see how many months until each debt is gone",
                "Rupee (₹) AND dollar ($) versions + 5 printable pages (PDF)"],
        who="Students, young professionals, couples and families who want a simple, honest view of their money.",
        how="Open in Excel, or in Google Sheets (File > Import). Type your numbers into the colored cells; "
            "everything else updates by itself.",
        note="For education and planning only, not financial advice.",
        social="Budget Planner 2027: does the math for you, Excel + Google Sheets"),
    "bloop_colouring_book": dict(
        hook="Big, friendly pictures little hands can actually color.",
        inside=["24 coloring pages: Bloop, Pip, Mo and Dee with apples, stars, ducks, balloons and more",
                "Thick, bold lines and one picture per page (no tiny details)",
                "A blank page at the end for their own drawing",
                "Printable PDF: print as many copies as your family needs"],
        who="Toddlers and preschoolers, ages 2-5. Great for quiet time, travel and rainy days.",
        how="Download the PDF, print at home on A4 or Letter paper, grab the crayons.",
        note="For personal and classroom use.",
        kdp="A first coloring book made for little hands: 24 big, simple pictures with thick lines, one per page, "
            "so toddlers and preschoolers (ages 2-5) can color inside the lines and feel proud. Friendly characters "
            "Bloop, Pip, Mo and Dee bring apples, stars, ducks and balloons to life, and the last page is left blank "
            "for their own drawing. A calm screen-free activity for quiet time, travel and rainy days.",
        social="24 big, easy coloring pages for ages 2-5. Print at home, any time"),
    "christmas_colouring_book": dict(
        hook="A cozy Christmas coloring book little hands can actually color.",
        inside=["20 Christmas pages: Bloop, Pip, Mo and Dee in Santa hats with trees, presents, snowmen, candy canes, "
                "bells, stockings, ornaments, stars, gingerbread men and reindeer",
                "Big pictures with thick, bold lines (no tiny details)",
                "A Letter to Santa page and a page for their own Christmas drawing",
                "Printable PDF: print as many copies as your family needs"],
        who="Toddlers and preschoolers, ages 2-6. Great for the Christmas holidays, classrooms and stocking stuffers.",
        how="Download the PDF, print at home on A4 or Letter paper, grab the crayons.",
        note="For personal and classroom use.",
        kdp="A cozy Christmas coloring book for little hands: 20 big, simple pictures with thick lines so toddlers and "
            "preschoolers (ages 2-6) can color with confidence. Bloop, Pip, Mo and Dee wear Santa hats next to "
            "Christmas trees, presents, snowmen, candy canes, jingle bells, stockings, ornaments, stars, gingerbread "
            "men and reindeer. Includes a Letter to Santa page and a page for their own Christmas drawing. A calm, "
            "screen-free holiday activity and a perfect stocking stuffer.",
        social="Christmas coloring pages for ages 2-6: Santa hats, trees, snowmen + a Letter to Santa"),
    "brain_snack_puzzle_book": dict(
        hook="34 puzzles that start easy and get satisfyingly hard.",
        inside=["10 themed word searches: space, ocean, animals, food, sports, science and more",
                "12 mazes and 12 sudoku, each from easy to hard",
                "Every answer at the back",
                "Large print, one puzzle per page"],
        who="Kids and teens (and puzzle-loving adults) who want a screen-free brain workout.",
        how="Download the PDF and print the pages you want, as often as you like.",
        note="Every maze has exactly one way through and every sudoku exactly one answer.",
        kdp="34 brain-boosting puzzles for kids and teens that start easy and get satisfyingly hard: 10 themed word "
            "searches (space, ocean, animals, food, sports, science and more), 12 mazes and 12 sudoku. Large print with "
            "one puzzle per page, and every answer at the back. Every maze has exactly one way through and every "
            "sudoku exactly one solution. A screen-free gift for road trips, holidays and rainy afternoons.",
        social="34 puzzles, easy to hard: word search, mazes, sudoku. Answers included"),
}
MUSIC = {
    "cosmic": ("Space & cosmos", "slow wide pads and starry shimmer", "space facts, science explainers, sleep and study videos"),
    "devotional": ("Indian devotional", "calm, sacred melodies", "spiritual stories, festival posts, mythology and meditation videos"),
    "dhol": ("Dhol & stadium energy", "high-energy Indian beats", "cricket edits, sports hype, celebration and wedding reels"),
    "ocean": ("Deep ocean documentary", "cinematic depth and mystery", "ocean facts, nature documentaries and travel films"),
    "retro": ("Retro Bollywood nostalgia", "warm, vintage film vibes", "Bollywood facts, throwback reels and vlogs"),
    "wild": ("Wildlife documentary", "cinematic nature themes", "animal facts, safari footage and nature channels"),
}


def _music(pid: str) -> dict | None:
    key = pid.replace("music_pack_", "")
    if key not in MUSIC:
        return None
    name, mood, use = MUSIC[key]
    return dict(
        hook=f"{name} music that makes your videos feel finished: {mood}.",
        inside=["5 original tracks, 90 seconds each (high-quality MP3)",
                "Each track builds, breathes and peaks, so it fits a story",
                "A license file (LICENSE.txt) you can show any platform"],
        who=f"YouTubers, Reels and Shorts creators, podcasters and editors making {use}.",
        how="Download, drop into your editor, publish. Loop or cut anywhere.",
        note="Royalty-free for monetized videos and client work, no credit needed. Content ID-free: never registered, "
             "so your videos won't get claims. Reselling the music itself is not allowed.",
        social=f"5 no-copyright {name.title()} tracks for your videos")


def _free(pid: str) -> dict | None:
    """A free sample: honest about being a sample, points to the full version (lead magnet)."""
    from .store_covers import FREEBIES
    parent = pid[len("free_"):]
    fb, base = FREEBIES.get(parent), COPY.get(parent)
    if not (pid.startswith("free_") and fb and base):
        return None
    return dict(
        hook=f"Try it free: {fb['what']}, straight from our full printable.",
        inside=[f"{fb['what'][0].upper()}{fb['what'][1:]}", "US Letter PDF (prints on A4 with 'fit to page')",
                "A last page with a link to the full version if you'd like more"],
        who=base["who"],
        how="Get it free, download, print as many copies as you need for your home or class.",
        note="Free for personal and classroom use. Please don't resell or re-share the file itself.",
        social=f"Free printable: {fb['what']}")


def copy_for(pid: str) -> dict:
    return COPY.get(pid) or _music(pid) or _free(pid) or {}


def description(pid: str, platform: str = "payhip") -> str:
    c = copy_for(pid)
    if not c:
        return ""
    if platform == "kdp":
        return c.get("kdp", c["hook"] + " " + " ".join(c["inside"]))
    if platform == "social":
        return c["social"]
    lines = [c["hook"], "", "WHAT'S INSIDE"] + [f"✔ {x}" for x in c["inside"]]
    lines += ["", "WHO IT'S FOR", c["who"], "", "HOW IT WORKS", c["how"]]
    if c.get("note"):
        lines += ["", c["note"]]
    tail = ("Instant download." if pid.startswith("free_") else "Instant download right after purchase.")         if platform in ("payhip", "gumroad") else ""
    lines += ["", (tail + " Questions? Message us any time. Made by HookHouse Media.").strip()]
    return "\n".join(lines)
