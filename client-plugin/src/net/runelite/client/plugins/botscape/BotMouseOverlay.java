package net.runelite.client.plugins.botscape;

import java.awt.Dimension;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import net.runelite.api.Client;
import net.runelite.api.NPC;
import net.runelite.api.Perspective;
import net.runelite.api.Player;
import net.runelite.api.Point;
import net.runelite.api.SpritePixels;
import net.runelite.api.coords.LocalPoint;
import net.runelite.api.widgets.Widget;
import net.runelite.client.ui.overlay.Overlay;
import net.runelite.client.ui.overlay.OverlayLayer;
import net.runelite.client.ui.overlay.OverlayPosition;

/**
 * User-requested: the bot's clicks, drawn exactly like the game's own click cross: the game's
 * cross sprites (4 yellow frames for a walk, 4 red for an action), 100 ms a frame, centred where
 * it "clicked" (the npc, the object's tile, the walked-to tile, the inventory slot). The clicks come
 * from the gateway (/players/{name}/clicks), polled every 150 ms off the client thread; each one
 * animates from when this client first sees it.
 */
class BotMouseOverlay extends Overlay
{
	private static final int INVENTORY_GROUP = 149;
	private static final long FRAME_MS = 100;
	private static final int FRAMES = 4;

	private final Client client;
	private volatile List<Object> clicks = List.of();
	private volatile boolean running = true;
	/** When this client first saw each click (it animates from then). */
	private final Map<String, Long> seen = new HashMap<>();
	private BufferedImage[] sprites;

	BotMouseOverlay(Client client)
	{
		this.client = client;
		setPosition(OverlayPosition.DYNAMIC);
		setLayer(OverlayLayer.ABOVE_WIDGETS);
		Thread poller = new Thread(this::poll, "botscape-bot-mouse");
		poller.setDaemon(true);
		poller.start();
	}

	void stop()
	{
		running = false;
	}

	private void poll()
	{
		while (running)
		{
			try
			{
				Player me = client.getLocalPlayer();
				String name = me == null ? null : me.getName();
				clicks = name == null ? List.of()
					: Gateway.list(Gateway.map(Gateway.get("/players/" + Gateway.enc(name.toLowerCase()) + "/clicks")).get("clicks"));
			}
			catch (Exception e)
			{
				clicks = List.of();
			}
			try
			{
				Thread.sleep(150);
			}
			catch (InterruptedException e)
			{
				return;
			}
		}
	}

	/** The game's cross sprites as images: 0-3 yellow, 4-7 red. Read once, on the client thread. */
	private BufferedImage[] sprites()
	{
		if (sprites == null)
		{
			SpritePixels[] cross = client.getCrossSprites();
			if (cross == null || cross.length < 2 * FRAMES)
			{
				return null;
			}
			BufferedImage[] images = new BufferedImage[cross.length];
			for (int i = 0; i < cross.length; i++)
			{
				images[i] = cross[i] == null ? null : cross[i].toBufferedImage();
			}
			sprites = images;
		}
		return sprites;
	}

	@Override
	public Dimension render(Graphics2D g)
	{
		List<Object> now = clicks;
		BufferedImage[] cross = sprites();
		if (cross == null || client.getLocalPlayer() == null)
		{
			return null;
		}
		long time = System.currentTimeMillis();
		seen.values().removeIf(first -> time - first > 5000);
		for (Object o : now)
		{
			Map<String, Object> c = Gateway.map(o);
			String kind = Gateway.str(c.get("kind"));
			// The same click comes back in several polls: identify it by what and roughly when.
			long at = (time - Gateway.num(c.get("age"))) / 500;
			String key = kind + c.get("x") + "," + c.get("z") + "," + c.get("index") + "," + c.get("slot") + "@" + at;
			long first = seen.computeIfAbsent(key, k -> time);
			int frame = (int) ((time - first) / FRAME_MS);
			if (frame >= FRAMES)
			{
				continue;
			}
			Point p = point(kind, c);
			BufferedImage image = cross[("walk".equals(kind) ? 0 : FRAMES) + frame];
			if (p != null && image != null)
			{
				g.drawImage(image, p.getX() - image.getWidth() / 2, p.getY() - image.getHeight() / 2, null);
			}
		}
		return null;
	}

	/** Where on the screen the click was. */
	private Point point(String kind, Map<String, Object> c)
	{
		if ("slot".equals(kind))
		{
			Rectangle box = slotBounds(Gateway.num(c.get("slot")));
			return box == null ? null : new Point((int) box.getCenterX(), (int) box.getCenterY());
		}
		LocalPoint local = null;
		if ("npc".equals(kind))
		{
			NPC npc = client.getTopLevelWorldView().npcs().byIndex(Gateway.num(c.get("index")));
			local = npc == null ? null : npc.getLocalLocation();
		}
		else if (c.get("x") != null)
		{
			local = LocalPoint.fromWorld(client.getTopLevelWorldView(), Gateway.num(c.get("x")), Gateway.num(c.get("z")));
		}
		return local == null ? null : Perspective.localToCanvas(client, local, client.getTopLevelWorldView().getPlane());
	}

	private Rectangle slotBounds(int slot)
	{
		Widget inventory = client.getWidget(INVENTORY_GROUP, 0);
		if (inventory == null || inventory.isHidden())
		{
			return null;
		}
		Widget item = inventory.getChild(slot);
		return item == null ? null : item.getBounds();
	}
}
