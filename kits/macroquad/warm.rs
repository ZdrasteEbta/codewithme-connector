// Программа для прогрева: один раз собирает все крейты набора macroquad
use macroquad::prelude::*;

#[macroquad::main("CodeWithMe")]
async fn main() {
    loop {
        clear_background(DARKGRAY);
        draw_text("CodeWithMe", 20.0, 40.0, 30.0, WHITE);
        next_frame().await;
    }
}
