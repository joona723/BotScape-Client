package net.runelite.client.plugins.botscape;

import java.awt.BasicStroke;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Cursor;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.Insets;
import java.awt.RenderingHints;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.geom.Path2D;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import javax.swing.BorderFactory;
import javax.swing.ImageIcon;
import javax.swing.JButton;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingConstants;
import net.runelite.client.ui.ColorScheme;
import net.runelite.client.ui.FontManager;

/** Look and feel for the Bot Scape panels: drawn icons, rounded buttons, cards and pills. */
final class BotScapeUi
{
	static final Color GOLD = new Color(0xdc8a00);
	static final Color GREEN = new Color(0x2fa35a);
	static final Color GREEN_HOVER = new Color(0x38b866);
	static final Color RED = new Color(0xc9483f);
	static final Color RED_HOVER = new Color(0xdd564d);
	static final Color TEXT = new Color(0xe6e6e6);
	static final Color MUTED = new Color(0x9a9a9a);

	/** Text for a Swing HTML label: a name can't add markup. */
	static String esc(String text)
	{
		return text == null ? "" : text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
	}
	static final Color CARD = ColorScheme.DARKER_GRAY_COLOR;
	static final Color CARD_HOVER = ColorScheme.DARKER_GRAY_HOVER_COLOR;

	private BotScapeUi()
	{
	}

	// --- icons (assets/icons, drawn by Codex) -------------------------------------------------

	/** An icon from the plugin's resources, e.g. icon("play", 24) loads play-24.png. */
	static BufferedImage image(String name, int size)
	{
		return net.runelite.client.util.ImageUtil.loadImageResource(BotScapeUi.class, name + "-" + size + ".png");
	}

	static ImageIcon icon(String name, int size)
	{
		return new ImageIcon(image(name, size));
	}

	/** A bare icon button: no background, slightly brighter on hover. */
	static JButton iconButton(String name, int size, String tooltip)
	{
		ImageIcon normal = icon(name, size);
		JButton b = new JButton(normal);
		b.setRolloverIcon(new ImageIcon(net.runelite.client.util.ImageUtil.luminanceScale(image(name, size), 1.35f)));
		b.setContentAreaFilled(false);
		b.setBorderPainted(false);
		b.setFocusPainted(false);
		b.setOpaque(false);
		b.setBorder(BorderFactory.createEmptyBorder(2, 2, 2, 2));
		b.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
		b.setToolTipText(tooltip);
		return b;
	}

	// --- toolbar and button icons (fallback drawings) ----------------------------------------

	private static Graphics2D smooth(BufferedImage image)
	{
		Graphics2D g = image.createGraphics();
		g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
		g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL, RenderingHints.VALUE_STROKE_PURE);
		g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
		return g;
	}

	/** Toolbar icon for scripts: a green round play button. */
	static BufferedImage scriptsIcon()
	{
		BufferedImage image = new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		g.setColor(new Color(0x1d7a41));
		g.fillOval(0, 0, 16, 16);
		g.setColor(new Color(0x3fcf77));
		g.fillOval(1, 1, 14, 14);
		g.setColor(Color.WHITE);
		g.fill(triangle(6, 4.5, 8));
		g.dispose();
		return image;
	}

	/** Toolbar icon for the Bot Scape panel: a gold shield with a "B". */
	static BufferedImage familyIcon()
	{
		BufferedImage image = new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		Path2D shield = new Path2D.Double();
		shield.moveTo(8, 0.5);
		shield.lineTo(15, 3);
		shield.curveTo(15, 10, 11.5, 13.5, 8, 15.5);
		shield.curveTo(4.5, 13.5, 1, 10, 1, 3);
		shield.closePath();
		g.setColor(new Color(0x8a5600));
		g.fill(shield);
		g.setColor(GOLD);
		g.setStroke(new BasicStroke(1.2f));
		g.draw(shield);
		g.setColor(new Color(0xffd27a));
		g.setFont(new Font("Segoe UI", Font.BOLD, 10));
		g.drawString("B", 5, 12);
		g.dispose();
		return image;
	}

	/** Toolbar icon for the live map: a folded map with a location pin. */
	static BufferedImage mapIcon()
	{
		BufferedImage image = new BufferedImage(16, 16, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		Path2D map = new Path2D.Double();
		map.moveTo(1, 3);
		map.lineTo(5.5, 1.5);
		map.lineTo(10.5, 3);
		map.lineTo(15, 1.5);
		map.lineTo(15, 13);
		map.lineTo(10.5, 14.5);
		map.lineTo(5.5, 13);
		map.lineTo(1, 14.5);
		map.closePath();
		g.setColor(new Color(0x5e8f3a));
		g.fill(map);
		g.setColor(new Color(0x3a5e22));
		g.setStroke(new BasicStroke(1f));
		g.drawLine(5, 2, 5, 13);
		g.drawLine(10, 3, 10, 14);
		g.setColor(new Color(0xe05a52));
		g.fillOval(8, 4, 5, 5);
		g.fill(triangle(8.6, 7.5, 3.8, Math.PI / 2));
		g.setColor(Color.WHITE);
		g.fill(new java.awt.geom.Ellipse2D.Double(9.7, 5.7, 1.8, 1.8));
		g.dispose();
		return image;
	}

	static ImageIcon play(int size)
	{
		BufferedImage image = new BufferedImage(size, size, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		g.setColor(Color.WHITE);
		double s = size * 0.42;
		g.fill(triangle(size * 0.38, (size - s) / 2, s));
		g.dispose();
		return new ImageIcon(image);
	}

	static ImageIcon stop(int size)
	{
		BufferedImage image = new BufferedImage(size, size, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		g.setColor(Color.WHITE);
		double s = size * 0.36;
		g.fill(new RoundRectangle2D.Double((size - s) / 2, (size - s) / 2, s, s, 2, 2));
		g.dispose();
		return new ImageIcon(image);
	}

	static ImageIcon reload(int size, Color color)
	{
		BufferedImage image = new BufferedImage(size, size, BufferedImage.TYPE_INT_ARGB);
		Graphics2D g = smooth(image);
		g.setColor(color);
		g.setStroke(new BasicStroke(1.6f, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
		double m = size * 0.2;
		g.drawArc((int) m, (int) m, (int) (size - 2 * m), (int) (size - 2 * m), 30, 280);
		g.fill(triangle(size - m - 3, m - 2, 5, Math.PI / 2.4));
		g.dispose();
		return new ImageIcon(image);
	}

	/** A right-pointing triangle with its left edge at x, top at y. */
	private static Path2D triangle(double x, double y, double size)
	{
		return triangle(x, y, size, 0);
	}

	private static Path2D triangle(double x, double y, double size, double angle)
	{
		Path2D t = new Path2D.Double();
		t.moveTo(x, y);
		t.lineTo(x + size * 0.866, y + size / 2);
		t.lineTo(x, y + size);
		t.closePath();
		if (angle != 0)
		{
			t.transform(java.awt.geom.AffineTransform.getRotateInstance(angle, x + size / 2, y + size / 2));
		}
		return t;
	}

	// --- components --------------------------------------------------------------------------

	/** A flat rounded button with a hover colour. */
	static class RoundButton extends JButton
	{
		private final Color base;
		private final Color hover;
		private boolean over;
		private final boolean circle;

		RoundButton(String text, Color base, Color hover)
		{
			this(text, null, base, hover, false);
		}

		RoundButton(String text, ImageIcon icon, Color base, Color hover, boolean circle)
		{
			super(text, icon);
			this.base = base;
			this.hover = hover;
			this.circle = circle;
			setFont(FontManager.getRunescapeSmallFont());
			setForeground(Color.WHITE);
			setContentAreaFilled(false);
			setBorderPainted(false);
			setFocusPainted(false);
			setOpaque(false);
			setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
			setMargin(new Insets(4, 10, 4, 10));
			setIconTextGap(4);
			addMouseListener(new MouseAdapter()
			{
				@Override
				public void mouseEntered(MouseEvent e)
				{
					over = true;
					repaint();
				}

				@Override
				public void mouseExited(MouseEvent e)
				{
					over = false;
					repaint();
				}
			});
		}

		@Override
		protected void paintComponent(Graphics graphics)
		{
			Graphics2D g = (Graphics2D) graphics.create();
			g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
			g.setColor(!isEnabled() ? ColorScheme.MEDIUM_GRAY_COLOR : over ? hover : base);
			if (circle)
			{
				g.fillOval(0, 0, getWidth() - 1, getHeight() - 1);
			}
			else
			{
				g.fillRoundRect(0, 0, getWidth(), getHeight(), 8, 8);
			}
			g.dispose();
			super.paintComponent(graphics);
		}
	}

	static RoundButton circleButton(ImageIcon icon, Color base, Color hover, String tooltip)
	{
		RoundButton b = new RoundButton(null, icon, base, hover, true);
		b.setMargin(new Insets(0, 0, 0, 0));
		Dimension d = new Dimension(26, 26);
		b.setPreferredSize(d);
		b.setMinimumSize(d);
		b.setMaximumSize(d);
		b.setToolTipText(tooltip);
		return b;
	}

	/** A rounded card that highlights on hover. */
	static class Card extends JPanel
	{
		private boolean over;
		private Color accent;

		Card()
		{
			super(new BorderLayout(8, 0));
			setOpaque(false);
			setBorder(BorderFactory.createEmptyBorder(7, 9, 7, 7));
			setAlignmentX(Component.LEFT_ALIGNMENT);
			addMouseListener(new MouseAdapter()
			{
				@Override
				public void mouseEntered(MouseEvent e)
				{
					over = true;
					repaint();
				}

				@Override
				public void mouseExited(MouseEvent e)
				{
					if (!contains(e.getPoint()))
					{
						over = false;
						repaint();
					}
				}
			});
		}

		/** A coloured strip on the card's left edge (e.g. green while a script runs). */
		void setAccent(Color accent)
		{
			this.accent = accent;
			repaint();
		}

		@Override
		public Dimension getMaximumSize()
		{
			return new Dimension(Integer.MAX_VALUE, getPreferredSize().height);
		}

		@Override
		protected void paintComponent(Graphics graphics)
		{
			Graphics2D g = (Graphics2D) graphics.create();
			g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
			g.setColor(over ? CARD_HOVER : CARD);
			g.fillRoundRect(0, 0, getWidth(), getHeight(), 8, 8);
			if (accent != null)
			{
				g.setColor(accent);
				g.fillRoundRect(0, 0, 4, getHeight(), 4, 4);
			}
			g.dispose();
			super.paintComponent(graphics);
		}
	}

	/** A small rounded status label, e.g. "online" in green. */
	static class Pill extends JLabel
	{
		private Color fill;

		Pill(String text, Color fill)
		{
			super(text, SwingConstants.CENTER);
			setFont(FontManager.getRunescapeSmallFont());
			setForeground(Color.WHITE);
			setBorder(BorderFactory.createEmptyBorder(1, 7, 1, 7));
			this.fill = fill;
		}

		void set(String text, Color fill)
		{
			setText(text);
			this.fill = fill;
			repaint();
		}

		@Override
		protected void paintComponent(Graphics graphics)
		{
			Graphics2D g = (Graphics2D) graphics.create();
			g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
			g.setColor(fill);
			g.fillRoundRect(0, 0, getWidth(), getHeight(), getHeight(), getHeight());
			g.dispose();
			super.paintComponent(graphics);
		}
	}

	static JLabel label(String text, Color color, Font font)
	{
		JLabel l = new JLabel(text);
		l.setFont(font);
		l.setForeground(color);
		l.setAlignmentX(Component.LEFT_ALIGNMENT);
		return l;
	}

	static JLabel small(String text, Color color)
	{
		return label(text, color, FontManager.getRunescapeSmallFont());
	}

	static JLabel bold(String text, Color color)
	{
		return label(text, color, FontManager.getRunescapeBoldFont());
	}

	/** A section heading with an optional component on the right. */
	static JPanel header(String title, Component right)
	{
		JPanel row = new JPanel(new BorderLayout());
		row.setOpaque(false);
		row.setAlignmentX(Component.LEFT_ALIGNMENT);
		row.setBorder(BorderFactory.createEmptyBorder(12, 0, 6, 0));
		row.add(bold(title, Color.WHITE), BorderLayout.WEST);
		if (right != null)
		{
			row.add(right, BorderLayout.EAST);
		}
		row.setMaximumSize(new Dimension(Integer.MAX_VALUE, 34));
		return row;
	}

	static Color statusColor(String status)
	{
		switch (status)
		{
			case "online":
				return GREEN;
			case "logging_in":
				return GOLD;
			case "error":
				return RED;
			case "locked":
				return new Color(0x5a5a5a);
			default:
				return new Color(0x4a4a4a);
		}
	}
}
