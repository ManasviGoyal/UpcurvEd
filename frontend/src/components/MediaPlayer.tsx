// frontend/src/components/MediaPlayer.tsx
import { useState, useRef, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize,
  Minimize,
  Download,
  ExternalLink,
  VideoIcon,
  Music,
} from 'lucide-react';

interface MediaPlayerProps {
  videoUrl?: string;
  audioUrl?: string;
  subtitleUrl?: string;
  title?: string;
  className?: string;
  onExpand?: () => void; // Callback to open in sidebar player
  variant?: 'full' | 'thumbnail'; // New prop for different display modes
  gradientClass?: string; // Tailwind gradient stops (e.g., from-sky-500 via-indigo-500 to-violet-600)
}

export const MediaPlayer = ({
  videoUrl,
  audioUrl,
  subtitleUrl,
  title,
  className = "",
  onExpand,
  variant = 'full',
  gradientClass = ''
}: MediaPlayerProps) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState([75]);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const mediaUrl = videoUrl || audioUrl;
  const isVideo = !!videoUrl;

  // Reset state when media URL changes
  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
  }, [mediaUrl]);

  useEffect(() => {
    const media = mediaRef.current;
    if (!media) return;

    const updateTime = () => setCurrentTime(media.currentTime);
    const updateDuration = () => setDuration(media.duration || 0);
    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);
    const handleEnded = () => setIsPlaying(false);

    media.addEventListener('timeupdate', updateTime);
    media.addEventListener('loadedmetadata', updateDuration);
    media.addEventListener('play', handlePlay);
    media.addEventListener('pause', handlePause);
    media.addEventListener('ended', handleEnded);

    return () => {
      media.removeEventListener('timeupdate', updateTime);
      media.removeEventListener('loadedmetadata', updateDuration);
      media.removeEventListener('play', handlePlay);
      media.removeEventListener('pause', handlePause);
      media.removeEventListener('ended', handleEnded);
    };
  }, [mediaUrl]);

  const togglePlayPause = () => {
    const media = mediaRef.current;
    if (!media) return;

    if (isPlaying) {
      media.pause();
    } else {
      media.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleSeek = (value: number[]) => {
    const media = mediaRef.current;
    if (!media || !duration) return;

    const newTime = (value[0] / 100) * duration;
    media.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const handleVolumeChange = (value: number[]) => {
    const media = mediaRef.current;
    if (!media) return;

    setVolume(value);
    media.volume = value[0] / 100;
  };

  const skipTime = (seconds: number) => {
    const media = mediaRef.current;
    if (!media) return;

    media.currentTime = Math.max(0, Math.min(duration, media.currentTime + seconds));
  };

  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  const toggleFullscreen = async () => {
    if (!containerRef.current) return;

    try {
      if (!isFullscreen) {
        if (containerRef.current.requestFullscreen) {
          await containerRef.current.requestFullscreen();
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        }
      }
    } catch (error) {
      console.error('Fullscreen error:', error);
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const handleDownload = () => {
    if (!mediaUrl) return;
    const link = document.createElement('a');
    link.href = mediaUrl;
    link.download = title || (isVideo ? 'video.mp4' : 'audio.mp3');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  if (!mediaUrl) return null;

  // Thumbnail variant for chat messages (ChatGPT style)
  if (variant === 'thumbnail') {
    return (
      <div
        className={`bg-card border rounded-lg p-3 cursor-pointer hover:bg-accent transition-colors ${className}`}
        onClick={onExpand}
      >
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-gradient-to-br ${gradientClass}`}>
            {isVideo ? (
              <VideoIcon className="w-5 h-5 text-white" />
            ) : (
              <Music className="w-5 h-5 text-white" />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm truncate">
              {title || (isVideo ? 'Generated Video' : 'Generated Podcast')}
            </p>
            <p className="text-xs text-muted-foreground">
              Click to play in media player
            </p>
          </div>
          <ExternalLink className="w-4 h-4 text-muted-foreground flex-shrink-0" />
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`bg-card border rounded-lg p-4 space-y-3 ${className}`}>
      {/* Title */}
      {title && (
        <div className="flex items-center justify-between">
          <h4 className="font-medium text-sm">{title}</h4>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              onClick={handleDownload}
              className="h-10 w-10 p-0"
            >
              <Download className="w-5 h-5" />
            </Button>
          </div>
        </div>
      )}

      {/* Media Element */}
      {isVideo ? (
        <video
          ref={mediaRef as React.RefObject<HTMLVideoElement>}
          src={videoUrl}
          key={(videoUrl || '') + (subtitleUrl || '')}
          className="w-full aspect-video bg-black rounded video-cc"
          preload="metadata"
        >
          {subtitleUrl && (
            <track
              kind="subtitles"
              src={subtitleUrl}
              srcLang="en"
              default
            />
          )}
        </video>
      ) : (
        <div className="relative">
          <audio
            ref={mediaRef as React.RefObject<HTMLAudioElement>}
            src={audioUrl}
            preload="metadata"
            className="hidden"
          />
          {/* Audio Waveform Placeholder */}
          <div className="w-full h-24 bg-secondary rounded flex items-center justify-center">
            <div className="flex gap-1 items-end h-12">
              {Array.from({ length: 20 }).map((_, i) => (
                <div
                  key={i}
                  className="w-1 bg-primary rounded animate-pulse"
                  style={{
                    height: `${20 + Math.random() * 60}%`,
                    animationDelay: `${i * 0.1}s`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Progress Bar */}
      <div className="space-y-2">
        <Slider
          value={[progressPercent]}
          onValueChange={handleSeek}
          max={100}
          step={0.1}
          className="cursor-pointer"
        />
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{formatTime(currentTime)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            onClick={() => skipTime(-10)}
            className="h-16 w-16 p-0"
          >
            <SkipBack className="w-8 h-8" />
          </Button>

          <Button
            onClick={togglePlayPause}
            className={`h-20 w-20 p-0 text-white bg-gradient-to-br ${gradientClass} hover:opacity-90`}
          >
            {isPlaying ? (
              <Pause className="w-10 h-10" />
            ) : (
              <Play className="w-10 h-10 ml-0.5" />
            )}
          </Button>

          <Button
            variant="ghost"
            onClick={() => skipTime(10)}
            className="h-16 w-16 p-0"
          >
            <SkipForward className="w-8 h-8" />
          </Button>
        </div>

        <div className="flex items-center gap-2">
          {/* Volume Control */}
          <div className="flex items-center gap-2 w-26">
            <Volume2 className="w-4 h-4 text-muted-foreground" />
            <Slider
              aria-label="Volume"
              value={volume}
              onValueChange={handleVolumeChange}
              max={100}
              step={1}
              className="flex-1"
            />
          </div>

          {/* Fullscreen Button */}
          {isVideo && (
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleFullscreen}
              className="h-8 w-8 p-0"
            >
              {isFullscreen ? (
                <Minimize className="w-4 h-4" />
              ) : (
                <Maximize className="w-4 h-4" />
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
