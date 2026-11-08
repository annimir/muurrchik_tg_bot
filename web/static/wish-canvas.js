class WishCanvasAnimation {
    constructor(container, {rarity = 3, radiant = false, onComplete}) {
        this.container = container;
        this.rarity = rarity;
        this.radiant = radiant;
        this.onComplete = onComplete;
        this.duration = 3000;
        this.completed = false;
        this.stars = this.createParticles(65);
        this.sparks = this.createParticles(32);
        this.clouds = this.createParticles(18);
        this.resize = this.resize.bind(this);
        this.tick = this.tick.bind(this);
    }

    createParticles(count) {
        return Array.from({length: count}, (_, index) => ({
            x: this.random(index * 3 + 1),
            y: this.random(index * 5 + 2),
            size: 0.6 + this.random(index * 7 + 3) * 2.4,
            speed: 0.5 + this.random(index * 11 + 4) * 1.5,
            phase: this.random(index * 13 + 5) * Math.PI * 2,
        }));
    }

    random(seed) {
        const value = Math.sin(seed * 91.173 + 17.71) * 43758.5453;
        return value - Math.floor(value);
    }

    palette() {
        if (this.radiant) {
            return {main: '#f4b4ff', secondary: '#9be7ff', glow: '#e6a5ff'};
        }
        return {
            3: {main: '#83c9ff', secondary: '#d8f2ff', glow: '#70aef5'},
            4: {main: '#c5a4ed', secondary: '#f0d5ff', glow: '#aa7ce4'},
            5: {main: '#ffd76a', secondary: '#fff2bd', glow: '#f4bd52'},
        }[this.rarity];
    }

    start() {
        this.canvas = document.createElement('canvas');
        this.canvas.className = 'wish-canvas';
        this.canvas.setAttribute('aria-label', 'Анимация молитвы');
        this.container.appendChild(this.canvas);
        window.addEventListener('resize', this.resize);
        this.resize();
        this.startedAt = performance.now();
        this.frameId = requestAnimationFrame(this.tick);
    }

    resize() {
        if (!this.canvas) {
            return;
        }
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const width = this.container.clientWidth;
        const height = this.container.clientHeight || 320;
        this.canvas.width = Math.max(1, Math.round(width * ratio));
        this.canvas.height = Math.max(1, Math.round(height * ratio));
        this.canvas.style.width = `${width}px`;
        this.canvas.style.height = `${height}px`;
        this.context = this.canvas.getContext('2d');
        this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    tick(now) {
        const progress = Math.min((now - this.startedAt) / this.duration, 1);
        this.draw(progress);
        if (progress >= 1) {
            this.complete();
            return;
        }
        this.frameId = requestAnimationFrame(this.tick);
    }

    complete() {
        if (this.completed) {
            return;
        }
        this.completed = true;
        this.destroy();
        if (this.onComplete) {
            this.onComplete();
        }
    }

    destroy() {
        if (this.frameId) {
            cancelAnimationFrame(this.frameId);
        }
        window.removeEventListener('resize', this.resize);
        this.canvas?.remove();
    }

    draw(progress) {
        const context = this.context;
        const width = this.container.clientWidth;
        const height = this.container.clientHeight || 320;
        context.clearRect(0, 0, width, height);
        this.drawBackground(context, width, height, progress);
        context.save();
        if (progress > 0.25 && progress < 0.6) {
            const strength = Math.sin(progress * Math.PI * 9) * (1 - progress) * 3;
            context.translate(strength, -strength * 0.5);
        }
        this.drawMeteor(context, width, height, progress);
        this.drawImpact(context, width, height, progress);
        context.restore();
        if (progress > 0.78) {
            context.fillStyle = `rgba(7, 17, 30, ${Math.min((progress - 0.78) / 0.22, 1)})`;
            context.fillRect(0, 0, width, height);
        }
    }

    drawBackground(context, width, height, progress) {
        const gradient = context.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, '#061225');
        gradient.addColorStop(0.65, '#173e70');
        gradient.addColorStop(1, '#739acb');
        context.fillStyle = gradient;
        context.fillRect(0, 0, width, height);
        this.stars.forEach((star, index) => {
            const alpha = 0.18 + Math.abs(Math.sin(progress * 12 * star.speed + star.phase + index)) * 0.55;
            context.fillStyle = `rgba(215, 235, 255, ${alpha})`;
            context.beginPath();
            context.arc(star.x * width, star.y * height * 0.72, star.size * 0.55, 0, Math.PI * 2);
            context.fill();
        });
        this.clouds.forEach((cloud, index) => {
            const x = cloud.x * width + Math.sin(progress * 2 + cloud.phase) * 16;
            const y = height * (0.88 + cloud.y * 0.16);
            const radius = width * (0.055 + cloud.size * 0.014);
            context.fillStyle = `rgba(221, 239, 255, ${0.2 + (index % 3) * 0.11})`;
            context.beginPath();
            context.ellipse(x, y, radius, radius * 0.42, 0, 0, Math.PI * 2);
            context.fill();
        });
    }

    drawMeteor(context, width, height, progress) {
        if (progress > 0.62) {
            return;
        }
        const palette = this.palette();
        const travel = Math.min(progress / 0.42, 1);
        const eased = 1 - Math.pow(1 - travel, 3);
        const start = {x: -width * 0.12, y: -height * 0.18};
        const end = {x: width * 0.68, y: height * 0.62};
        const head = {
            x: start.x + (end.x - start.x) * eased,
            y: start.y + (end.y - start.y) * eased,
        };
        const angle = Math.atan2(end.y - start.y, end.x - start.x);
        const direction = {x: Math.cos(angle), y: Math.sin(angle)};
        const tailLength = width * 0.72;
        context.save();
        context.globalCompositeOperation = 'lighter';
        for (let index = 0; index < 22; index += 1) {
            const fraction = index / 22;
            const x = head.x - direction.x * tailLength * fraction;
            const y = head.y - direction.y * tailLength * fraction;
            const nextX = head.x - direction.x * tailLength * (fraction + 0.055);
            const nextY = head.y - direction.y * tailLength * (fraction + 0.055);
            context.strokeStyle = this.rgba(palette.main, (1 - fraction) * 0.65);
            context.lineWidth = Math.max(0.7, (1 - fraction) * 18);
            context.lineCap = 'round';
            context.shadowColor = palette.glow;
            context.shadowBlur = 18 * (1 - fraction);
            context.beginPath();
            context.moveTo(x, y);
            context.lineTo(nextX, nextY);
            context.stroke();
        }
        this.sparks.forEach((spark, index) => {
            const distance = spark.y * tailLength * 0.8;
            const spread = (spark.x - 0.5) * 55 * (1 - travel * 0.3);
            const x = head.x - direction.x * distance + direction.y * spread;
            const y = head.y - direction.y * distance - direction.x * spread;
            const alpha = Math.max(0, Math.sin(progress * 10 + spark.phase + index)) * 0.65;
            context.fillStyle = this.rgba(palette.secondary, alpha);
            context.beginPath();
            context.arc(x, y, spark.size * 0.7, 0, Math.PI * 2);
            context.fill();
        });
        context.translate(head.x, head.y);
        context.rotate(angle + Math.PI / 4);
        context.shadowColor = '#ffffff';
        context.shadowBlur = 28;
        context.fillStyle = '#ffffff';
        context.beginPath();
        context.moveTo(0, -18);
        context.lineTo(4, -4);
        context.lineTo(18, 0);
        context.lineTo(4, 4);
        context.lineTo(0, 18);
        context.lineTo(-4, 4);
        context.lineTo(-18, 0);
        context.lineTo(-4, -4);
        context.closePath();
        context.fill();
        context.restore();
    }

    drawImpact(context, width, height, progress) {
        if (progress < 0.27) {
            return;
        }
        const palette = this.palette();
        const impact = Math.min((progress - 0.27) / 0.48, 1);
        const x = width * 0.68;
        const y = height * 0.62;
        context.save();
        context.globalCompositeOperation = 'lighter';
        const flash = Math.sin(impact * Math.PI);
        const glow = context.createRadialGradient(x, y, 0, x, y, 120 + impact * 90);
        glow.addColorStop(0, this.rgba('#ffffff', flash * 0.95));
        glow.addColorStop(0.12, this.rgba(palette.secondary, flash * 0.75));
        glow.addColorStop(0.5, this.rgba(palette.glow, flash * 0.22));
        glow.addColorStop(1, this.rgba(palette.glow, 0));
        context.fillStyle = glow;
        context.fillRect(x - 220, y - 220, 440, 440);
        context.strokeStyle = this.rgba('#ffffff', flash * 0.85);
        context.lineWidth = 2;
        context.shadowColor = '#ffffff';
        context.shadowBlur = 12;
        context.beginPath();
        context.moveTo(x - 160 - impact * 80, y);
        context.lineTo(x + 160 + impact * 80, y);
        context.stroke();
        const radius = 22 + impact * 105;
        const colors = ['#78ddff', '#a68bff', '#f0a4dd', '#ffd76a'];
        colors.forEach((color, index) => {
            context.strokeStyle = this.rgba(color, 0.85 * (1 - impact * 0.5));
            context.lineWidth = 3;
            context.beginPath();
            context.arc(x, y, radius, index * Math.PI / 2 + impact * 2, (index + 1) * Math.PI / 2 + impact * 2);
            context.stroke();
        });
        const beam = context.createLinearGradient(x, y - 190 * impact, x, y + 30);
        beam.addColorStop(0, this.rgba(palette.main, 0));
        beam.addColorStop(0.5, this.rgba('#ffffff', impact * 0.8));
        beam.addColorStop(1, this.rgba(palette.glow, 0));
        context.fillStyle = beam;
        context.shadowColor = palette.glow;
        context.shadowBlur = 20;
        context.fillRect(x - 4, y - 190 * impact, 8, 190 * impact + 30);
        context.restore();
    }

    rgba(hex, alpha) {
        const value = hex.replace('#', '');
        const number = parseInt(value, 16);
        const red = (number >> 16) & 255;
        const green = (number >> 8) & 255;
        const blue = number & 255;
        return `rgba(${red}, ${green}, ${blue}, ${Math.max(0, Math.min(alpha, 1))})`;
    }
}

window.WishCanvasAnimation = WishCanvasAnimation;
