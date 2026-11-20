import type { ComponentProps } from 'react';
import styles from './ToggleButton.module.css';

type Props = Omit<ComponentProps<'button'>, 'aria-pressed' | 'type'> & { pressed: boolean };

export function ToggleButton({ pressed, ...props }: Props) {
  return <button {...props} type="button" aria-pressed={pressed} className={styles.button} />;
}
