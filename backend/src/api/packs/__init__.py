"""Curated channel packs API module (TASK-038).

GET /packs — catalog list; POST /packs/{slug}/subscribe — subscribe in 1 click;
DELETE /packs/{slug}/subscribe — unsubscribe. Pack rows are watchlist rows with a
non-NULL `pack_slug` marker; they do NOT count toward the CHANNELS plan cap.
"""
